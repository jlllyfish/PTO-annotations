"""DN 02 — Pagination et vitesse de lecture des labels (lecture seule).

Mesure :
1. la taille de page maximale acceptée par `dossiers(first: …)` ;
2. le temps d'une lecture complète séquentielle (`number labels { id }`) ;
3. le temps d'une lecture découpée par état, en parallèle ;
et vérifie que les deux lectures renvoient exactement les mêmes dossiers.
"""

import asyncio
import time

from common import DN, env_int, save_result

STATES = ["en_construction", "en_instruction", "accepte", "refuse", "sans_suite"]
PAGE_SIZES = [100, 200, 500, 1000]

QUERY_ALL = """
query LabelsAll($n: Int!, $first: Int!, $after: String) {
  demarche(number: $n) {
    dossiers(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { number labels { id } }
    }
  }
}
"""

QUERY_STATE = """
query LabelsByState($n: Int!, $first: Int!, $after: String, $state: DossierState!) {
  demarche(number: $n) {
    dossiers(first: $first, after: $after, state: $state) {
      pageInfo { hasNextPage endCursor }
      nodes { number labels { id } }
    }
  }
}
"""


async def read_all(dn: DN, demarche: int, first: int, state: str | None = None) -> dict:
    query = QUERY_STATE if state else QUERY_ALL
    after, pages, nodes, total_bytes, errors = None, 0, [], 0, []
    start = time.perf_counter()
    while True:
        variables = {"n": demarche, "first": first, "after": after}
        if state:
            variables["state"] = state
        res = await dn.gql(query, variables)
        pages += 1
        total_bytes += res.bytes
        if not res.ok:
            errors.append({"status": res.status, "errors": res.errors, "headers": res.headers})
            break
        conn = res.data["demarche"]["dossiers"]
        nodes.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]
    return {
        "state": state,
        "pages": pages,
        "dossiers": len(nodes),
        "ms": round((time.perf_counter() - start) * 1000, 1),
        "octets": total_bytes,
        "errors": errors,
        "numbers": {n["number"] for n in nodes},
        "labels": {n["number"]: sorted(l["id"] for l in n["labels"]) for n in nodes},
    }


async def main() -> None:
    demarche = env_int("DN_DEMARCHE")
    dn = DN()
    out: dict = {}
    try:
        # 1. Taille de page maximale
        print("1. Taille de page acceptée")
        accepted = []
        out["tailles_page"] = []
        for size in PAGE_SIZES:
            res = await dn.gql(QUERY_ALL, {"n": demarche, "first": size, "after": None})
            n = len(res.data["demarche"]["dossiers"]["nodes"]) if res.ok else None
            print(f"   first={size:<5} → {'OK' if res.ok else 'refusé'} ({n} dossiers, {res.ms} ms)")
            out["tailles_page"].append(
                {"first": size, "ok": res.ok, "dossiers": n, "ms": res.ms, "errors": res.errors}
            )
            if res.ok:
                accepted.append(size)
        best = max(accepted) if accepted else 100
        print(f"   → taille retenue pour la suite : {best}")

        # 2. Lecture séquentielle complète
        print("\n2. Lecture complète séquentielle")
        seq = await read_all(dn, demarche, best)
        print(f"   {seq['dossiers']} dossiers, {seq['pages']} pages, {seq['ms']} ms, {seq['octets']} octets")

        # 3. Lecture parallèle par état
        print("\n3. Lecture parallèle par état")
        start = time.perf_counter()
        parts = await asyncio.gather(*(read_all(dn, demarche, best, s) for s in STATES))
        par_ms = round((time.perf_counter() - start) * 1000, 1)
        for p in parts:
            print(f"   {p['state']:<16} {p['dossiers']:>6} dossiers, {p['pages']} pages, {p['ms']} ms")
        par_numbers = set().union(*(p["numbers"] for p in parts))
        par_labels = {k: v for p in parts for k, v in p["labels"].items()}
        print(f"   total {len(par_numbers)} dossiers en {par_ms} ms "
              f"(gain ×{round(seq['ms'] / par_ms, 2) if par_ms else '?'})")

        same = par_numbers == seq["numbers"] and par_labels == seq["labels"]
        print(f"\nCohérence séquentiel / parallèle : {'identique ✅' if same else 'DIFFÉRENT ⚠️'}")
        if not same:
            print(f"   absents du parallèle : {sorted(seq['numbers'] - par_numbers)[:20]}")
            print(f"   absents du séquentiel : {sorted(par_numbers - seq['numbers'])[:20]}")

        nb_labels = sum(len(v) for v in seq["labels"].values())
        out.update({
            "taille_retenue": best,
            "sequentiel": {k: seq[k] for k in ("dossiers", "pages", "ms", "octets", "errors")},
            "parallele": {
                "ms": par_ms,
                "dossiers": len(par_numbers),
                "par_etat": [{k: p[k] for k in ("state", "dossiers", "pages", "ms", "errors")} for p in parts],
            },
            "coherent": same,
            "labels_poses_total": nb_labels,
        })
        save_result("dn_02_pagination", out)
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
