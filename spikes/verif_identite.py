"""Vérification préalable du contrôle « instructeur » (ÉCRIT dans Grist, sur une table temporaire).

1. Grist : quels attributs de `user` une formule déclenchée reçoit-elle (Email, UserID, Name, Access…) ?
   Une valeur forcée par l'appelant est-elle écrasée (variantes de recalcul) ?
2. Grist : la clé de service (propriétaire) peut-elle lire les membres du document (identifiant → adresse, rôle) ?
3. DN : le jeton lit-il les groupes instructeurs, leurs instructeurs (adresses) et le groupe d'un dossier ?

Les adresses ne sont jamais affichées en clair ni enregistrées (masquées : j***@domaine).
Lancer avec : python verif_identite.py --ecrire
"""

import asyncio

from common import DN, Grist, env_int, env_list, require_flag, save_result

TABLE = "LBL_Sessions_Test"
ATTRIBUTS = ["Email", "Name", "UserID", "UserRef", "Access", "SessionID", "IsLoggedIn"]
FAUX = "faux@exemple.fr"

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


def masque(v):
    if isinstance(v, str) and "@" in v:
        nom, dom = v.split("@", 1)
        return f"{nom[:1]}***@{dom}"
    return v


def trigger(formule: str, recalc_when: int) -> dict:
    return {"type": "Any", "isFormula": False, "formula": formule, "recalcWhen": recalc_when}


async def tester_grist(out: dict) -> None:
    grist = Grist()
    cree = False
    try:
        if TABLE in await grist.table_ids():
            raise SystemExit(f"La table {TABLE} existe déjà : supprimez-la avant de relancer.")
        cree = True
        colonnes = [{"id": "note", "fields": {"type": "Text"}}]
        colonnes += [{"id": f"u_{a}", "fields": trigger(f"user.{a}", 0)} for a in ATTRIBUTS]
        # Variantes anti-falsification pour la colonne d'identité
        colonnes += [
            {"id": "id_a", "fields": trigger("user.UserID", 0)},   # sera rendue dépendante d'elle-même
            {"id": "id_b", "fields": trigger("user.UserID", 2)},   # recalcul à toute modification manuelle
        ]
        status, _, body = await grist.request("POST", "/tables", json={"tables": [{"id": TABLE, "columns": colonnes}]})
        print(f"Création de la table : HTTP {status}")
        if status != 200:
            out["grist"] = {"ok": False, "creation": str(body)[:300]}
            return
        # id_a : dépend d'elle-même (colonne « de nettoyage » : toute valeur écrite est recalculée)
        _, _, cols = await grist.request("GET", f"/tables/{TABLE}/columns")
        ref = next(c["fields"].get("colRef") for c in cols["columns"] if c["id"] == "id_a")
        status, _, body = await grist.request("PATCH", f"/tables/{TABLE}/columns",
                                              json={"columns": [{"id": "id_a", "fields": {"recalcDeps": ["L", ref]}}]})
        print(f"Colonne id_a dépendante d'elle-même : HTTP {status} {'' if status == 200 else body}")

        await grist.request("POST", f"/tables/{TABLE}/records", json={"records": [
            {"fields": {"note": "sonde"}},
            {"fields": {"note": "forcee", "id_a": 999999, "id_b": 999999}},
        ]})
        _, _, body = await grist.request("GET", f"/tables/{TABLE}/records")
        lignes = {r["fields"]["note"]: r for r in body.get("records", [])}
        sonde = lignes["sonde"]["fields"]
        print("Attributs reçus par une formule déclenchée (appel par clé API) :")
        for a in ATTRIBUTS:
            print(f"   user.{a:<10} = {masque(sonde.get(f'u_{a}'))!r}")
        forcee = lignes["forcee"]["fields"]
        print(f"Valeur forcée à la création : id_a = {forcee['id_a']!r}, id_b = {forcee['id_b']!r} (vrai : {sonde['u_UserID']!r})")

        # Modification après coup par l'appelant
        await grist.request("PATCH", f"/tables/{TABLE}/records", json={"records": [
            {"id": lignes["sonde"]["id"], "fields": {"id_a": 888888, "id_b": 888888}}]})
        _, _, body = await grist.request("GET", f"/tables/{TABLE}/records")
        apres = next(r["fields"] for r in body["records"] if r["fields"]["note"] == "sonde")
        print(f"Valeur modifiée après coup : id_a = {apres['id_a']!r}, id_b = {apres['id_b']!r}")
        vrai = sonde["u_UserID"]
        out["grist"] = {
            "attributs_remplis": {a: sonde.get(f"u_{a}") not in (None, "") for a in ATTRIBUTS},
            "acces": sonde.get("u_Access"),
            "id_a_creation_protegee": forcee["id_a"] == vrai, "id_b_creation_protegee": forcee["id_b"] == vrai,
            "id_a_modif_protegee": apres["id_a"] == vrai, "id_b_modif_protegee": apres["id_b"] == vrai,
        }
        out["_user_id"] = vrai
    finally:
        if cree and TABLE in await grist.table_ids():
            await grist.request("POST", "/apply", json=[["RemoveTable", TABLE]])
            print("   table temporaire supprimée")
        await grist.close()


async def tester_membres(out: dict) -> None:
    grist = Grist()
    try:
        status, _, body = await grist.request("GET", "/access")
        if status != 200:
            print(f"Membres du document : HTTP {status} {str(body)[:200]}")
            out["membres"] = {"ok": False, "status": status}
            return
        users = body.get("users", [])
        print(f"Membres du document (clé de service) : {len(users)}")
        for u in users[:10]:
            print(f"   id {u.get('id')!r:<8} {masque(u.get('email'))!r:<28} rôle {u.get('access')!r} (hérité : {u.get('parentAccess')!r})")
        moi = next((u for u in users if u.get("id") == out.get("_user_id")), None)
        print(f"   → l'identifiant de la sonde est retrouvé dans les membres : {'oui' if moi else 'NON'}")
        out["membres"] = {"ok": True, "nb": len(users), "sonde_retrouvee": bool(moi),
                          "emails_presents": all(u.get("email") for u in users)}
    finally:
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
            print(f"   n° {g['number']} « {g['label']} »{' (fermé)' if g['closed'] else ''} : "
                  f"{len(g['instructeurs'])} instructeur(s)")
        out["dn_groupes"] = {"ok": True, "nb": len(groupes)}
        dossiers = env_list("DN_TEST_DOSSIERS", required=False)
        if dossiers:
            r = await dn.gql(Q_DOSSIER, {"n": int(dossiers[0])})
            gi = (r.data or {}).get("dossier", {}).get("groupeInstructeur") if r.ok else None
            print(f"Groupe du dossier {dossiers[0]} : {gi}")
            out["dn_dossier"] = {"ok": gi is not None}
    finally:
        await dn.close()


async def main() -> None:
    require_flag("--ecrire", f"crée puis supprime une table temporaire {TABLE} dans le document Grist")
    out: dict = {}
    print("1. Grist : formules déclenchées")
    await tester_grist(out)
    print("\n2. Grist : membres du document")
    await tester_membres(out)
    print("\n3. DN : groupes instructeurs")
    await tester_dn(out)
    out.pop("_user_id", None)
    save_result("verif_identite", out)


if __name__ == "__main__":
    asyncio.run(main())
