"""DN 01 — Catalogue des labels et portée du jeton (lecture seule).

Vérifie :
- que le jeton lit bien la démarche de test et sa liste de labels ;
- (optionnel) que le jeton est REFUSÉ sur une démarche hors périmètre
  (DN_DEMARCHE_HORS_PERIMETRE) : c'est le test du moindre privilège.
"""

import asyncio

from common import DN, env_int, save_result

QUERY = """
query Catalogue($n: Int!) {
  demarche(number: $n) {
    id
    number
    title
    state
    labels { id name color }
  }
}
"""


async def main() -> None:
    demarche = env_int("DN_DEMARCHE")
    hors_perimetre = env_int("DN_DEMARCHE_HORS_PERIMETRE", required=False)
    dn = DN()
    try:
        res = await dn.gql(QUERY, {"n": demarche})
        print(f"Démarche {demarche} : HTTP {res.status}, {res.ms} ms")
        out = {"demarche": {"ok": res.ok, "status": res.status, "ms": res.ms, "errors": res.errors}}
        if res.ok:
            d = res.data["demarche"]
            print(f"  « {d['title']} » ({d['state']}) — {len(d['labels'])} label(s)")
            for label in d["labels"]:
                print(f"   - {label['name']:<30} {label['color']:<20} {label['id']}")
            out["demarche"]["labels"] = d["labels"]

        if hors_perimetre:
            res2 = await dn.gql(QUERY, {"n": hors_perimetre})
            refused = not res2.ok
            print(f"\nDémarche hors périmètre {hors_perimetre} : "
                  f"{'refusée ✅' if refused else 'ACCESSIBLE ⚠️ (jeton trop large)'}")
            out["hors_perimetre"] = {"refuse": refused, "status": res2.status, "errors": res2.errors}
        else:
            print("\n(DN_DEMARCHE_HORS_PERIMETRE non renseignée : test de portée ignoré)")
        out["headers"] = res.headers
        save_result("dn_01_catalogue", out)
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
