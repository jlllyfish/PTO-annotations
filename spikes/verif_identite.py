"""Vérification préalable du contrôle « instructeur » (ÉCRIT dans Grist, sur une table temporaire).

1. Grist : une colonne à formule déclenchée `user.Email` / `user.Access`, créée par l'API, est-elle
   bien remplie par Grist lui-même à la création d'une ligne ? (avec la clé API : on doit lire VOTRE adresse)
2. DN : le jeton lit-il les groupes instructeurs, leurs instructeurs (adresses) et le groupe d'un dossier ?

Lancer avec : python verif_identite.py --ecrire
"""

import asyncio

from common import DN, Grist, env_int, env_list, require_flag, save_result

TABLE = "LBL_Sessions_Test"

Q_GROUPES = """
query Groupes($n: Int!) {
  demarche(number: $n) {
    groupeInstructeurs { number label closed instructeurs { email } }
  }
}
"""
Q_DOSSIER = """
query Dossier($n: Int!) { dossier(number: $n) { number groupeInstructeur { number label } } }
"""


async def tester_grist(out: dict) -> None:
    grist = Grist()
    cree = False
    try:
        if TABLE in await grist.table_ids():
            raise SystemExit(f"La table {TABLE} existe déjà : supprimez-la avant de relancer.")
        cree = True
        colonnes = [
            {"id": "note", "fields": {"type": "Text"}},
            # Formules déclenchées à la création de la ligne (isFormula=false + formula + recalcWhen=0)
            {"id": "email", "fields": {"type": "Text", "isFormula": False, "formula": "user.Email", "recalcWhen": 0}},
            {"id": "acces", "fields": {"type": "Text", "isFormula": False, "formula": "user.Access", "recalcWhen": 0}},
        ]
        status, _, body = await grist.request("POST", "/tables", json={"tables": [{"id": TABLE, "columns": colonnes}]})
        print(f"Création de la table : HTTP {status}")
        if status != 200:
            out["grist"] = {"ok": False, "creation": body}
            return
        # Le client tente de forcer une fausse adresse : Grist doit l'ignorer ou l'écraser ?
        await grist.request("POST", f"/tables/{TABLE}/records",
                                              json={"records": [{"fields": {"note": "sonde"}},
                                                                {"fields": {"note": "falsifiee", "email": "faux@exemple.fr"}}]})
        status, _, body = await grist.sql(f'SELECT note, email, acces FROM "{TABLE}" ORDER BY id')
        lignes = [r["fields"] for r in body.get("records", [])]
        for l in lignes:
            print(f"   ligne « {l['note']} » → email = {l['email']!r}, accès = {l['acces']!r}")
        out["grist"] = {
            "ok": bool(lignes and lignes[0]["email"]),
            "acces": lignes[0]["acces"] if lignes else None,
            "falsification_ignoree": len(lignes) > 1 and lignes[1]["email"] != "faux@exemple.fr",
        }
    finally:
        if cree and TABLE in await grist.table_ids():
            await grist.request("POST", "/apply", json=[["RemoveTable", TABLE]])
            print("   table temporaire supprimée")
        await grist.close()


async def tester_dn(out: dict) -> None:
    dn = DN()
    try:
        res = await dn.gql(Q_GROUPES, {"n": env_int("DN_DEMARCHE")})
        if not res.ok:
            print(f"Groupes instructeurs : refusé (HTTP {res.status}) {res.errors}")
            out["dn_groupes"] = {"ok": False, "errors": res.errors}
            return
        groupes = res.data["demarche"]["groupeInstructeurs"]
        print(f"Groupes instructeurs : {len(groupes)}")
        for g in groupes:
            emails = [i["email"] for i in g["instructeurs"]]
            print(f"   n° {g['number']} « {g['label']} »{' (fermé)' if g['closed'] else ''} : {len(emails)} instructeur(s)")
        out["dn_groupes"] = {"ok": True, "nb": len(groupes),
                             "instructeurs_par_groupe": [len(g["instructeurs"]) for g in groupes]}
        dossiers = env_list("DN_TEST_DOSSIERS", required=False)
        if dossiers:
            r = await dn.gql(Q_DOSSIER, {"n": int(dossiers[0])})
            gi = (r.data or {}).get("dossier", {}).get("groupeInstructeur") if r.ok else None
            print(f"Groupe du dossier {dossiers[0]} : {gi}")
            out["dn_dossier"] = {"ok": gi is not None, "groupe": gi}
    finally:
        await dn.close()


async def main() -> None:
    require_flag("--ecrire", f"crée puis supprime une table temporaire {TABLE} dans le document Grist")
    out: dict = {}
    print("1. Grist : formules déclenchées user.Email / user.Access")
    await tester_grist(out)
    print("\n2. DN : groupes instructeurs")
    await tester_dn(out)
    save_result("verif_identite", out)  # les adresses ne sont pas enregistrées, seulement des comptes


if __name__ == "__main__":
    asyncio.run(main())
