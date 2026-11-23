"""ANN 01 — Catalogue des annotations privées et identifiants (LECTURE SEULE).

Questions :
1. Le jeton lit-il `activeRevision.annotationDescriptors` (id, libellé, type, options des listes) ?
2. Le jeton lit-il les identifiants des instructeurs (`groupeInstructeurs.instructeurs { id email }`) ?
3. L'`id` d'une annotation est-il le même d'un dossier à l'autre ? Quel lien avec `champDescriptorId`
   et avec l'`id` du descripteur ? (détermine s'il faut lire chaque dossier avant d'écrire)
4. Quelles valeurs typées renvoie DN pour chaque type (pour comparer avec Grist) ?

Lancer avec : python ann_01_catalogue.py
Ensuite, recopier dans .env : DN_TEST_ANNOTATION_IDS (annotations de type texte et/ou case à cocher)
et DN_TEST_INSTRUCTEUR_EMAIL (votre adresse d'instructeur).
"""

import asyncio
from collections import defaultdict

from common import DN, env_int, env_list, save_result
from dn_annotations import Q_CATALOGUE, get_dossier


async def main() -> None:
    demarche = env_int("DN_DEMARCHE")
    numeros = [int(n) for n in env_list("DN_TEST_DOSSIERS")]
    dn = DN()
    out: dict = {}
    try:
        res = await dn.gql(Q_CATALOGUE, {"n": demarche})
        if not res.ok:
            raise SystemExit(f"Catalogue illisible : HTTP {res.status} {res.errors}")
        d = res.data["demarche"]
        descripteurs = d["activeRevision"]["annotationDescriptors"]
        print(f"1. Démarche {d['number']} — {len(descripteurs)} annotation(s) privée(s) ({res.ms} ms)")
        for a in descripteurs:
            options = f"  options={a.get('options')}" if a.get("options") is not None else ""
            print(f"   {a['__typename']:<38} {a['id']:<28} {a['label']}{options}")

        instructeurs = {i["email"]: i["id"] for g in d["groupeInstructeurs"] for i in g["instructeurs"]}
        print(f"\n2. {len(d['groupeInstructeurs'])} groupe(s), {len(instructeurs)} instructeur(s) avec identifiant"
              + ("" if instructeurs else "  ⚠️ aucun identifiant lisible"))
        for g in d["groupeInstructeurs"]:
            print(f"   groupe {g['number']} « {g['label']} »{' (fermé)' if g['closed'] else ''} : "
                  f"{len(g['instructeurs'])} instructeur(s)")

        print("\n3. Identifiants des annotations d'un dossier à l'autre")
        ids_par_desc: dict[str, set[str]] = defaultdict(set)
        dossiers = []
        for n in numeros:
            dos = await get_dossier(dn, n)
            dossiers.append(dos)
            for a in dos["annotations"]:
                ids_par_desc[a["champDescriptorId"]].add(a["id"])
        ids_desc = {a["id"] for a in descripteurs}
        stables = all(len(v) == 1 for v in ids_par_desc.values())
        egal_desc = all(next(iter(v)) in ids_desc for v in ids_par_desc.values()) if stables else False
        lien_desc = all(k in ids_desc for k in ids_par_desc)
        print(f"   id identique sur tous les dossiers : {'oui' if stables else 'NON'}")
        print(f"   id de l'annotation = id du descripteur : {'oui' if egal_desc else 'non'}")
        print(f"   champDescriptorId = id du descripteur : {'oui' if lien_desc else 'non'}")

        print("\n4. Valeurs du premier dossier")
        for a in dossiers[0]["annotations"] if dossiers else []:
            typed = {k: a[k] for k in ("texte", "coche", "ouiNon", "date", "entier", "choix", "choixMultiples") if k in a}
            print(f"   {a['__typename']:<28} {a['label'][:40]:<40} string={a['stringValue']!r} typé={typed} maj={a['updatedAt']}")

        out = {
            "descripteurs": descripteurs,
            "nb_instructeurs_avec_id": len(instructeurs),
            "ids_stables": stables,
            "id_annotation_egal_descripteur": egal_desc,
            "champDescriptorId_egal_descripteur": lien_desc,
            "ids_par_descripteur": {k: sorted(v) for k, v in ids_par_desc.items()},
            "dossiers": dossiers,
        }
        save_result("ann_01_catalogue", out)
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
