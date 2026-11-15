"""DN 02b — Deux pistes pour accélérer la lecture des labels (lecture seule).

A. Découpage par date de création : DN_FLUX lectures parallèles (défaut 6), chacune démarrant
   à une date (`createdSince`, tri ASC) et s'arrêtant là où commence la suivante.
   Comparée à une lecture séquentielle de référence : mêmes dossiers, mêmes labels ?
B. Rafraîchissement ciblé : `dossier(number:)` groupé par alias (25, 50, 100 par requête).
"""

import asyncio
import random
import time
from datetime import datetime, timedelta

from common import DN, env_int, save_result
from dn_02_pagination import read_all

Q_RANGE = """
query Range($n: Int!, $order: Order!) {
  demarche(number: $n) { dossiers(first: 1, order: $order) { nodes { number dateDepot } } }
}
"""

Q_FAN = """
query Fan($n: Int!, $after: String, $since: ISO8601DateTime!) {
  demarche(number: $n) {
    dossiers(first: 100, after: $after, createdSince: $since, order: ASC) {
      pageInfo { hasNextPage endCursor }
      nodes { number labels { id } }
    }
  }
}
"""


def build_multi(n: int) -> str:
    decl = ", ".join(f"$n{k}: Int!" for k in range(n))
    body = "\n".join(f"  d{k}: dossier(number: $n{k}) {{ number labels {{ id }} }}" for k in range(n))
    return f"query Multi({decl}) {{\n{body}\n}}"


async def page(dn: DN, demarche: int, since: str, after: str | None) -> dict:
    res = await dn.gql(Q_FAN, {"n": demarche, "since": since, "after": after})
    if not res.ok:
        raise RuntimeError(f"HTTP {res.status} {res.errors}")
    return res.data["demarche"]["dossiers"]


async def fan_out(dn: DN, demarche: int, flux: int) -> tuple[dict, list[dict]]:
    # Bornes : de la date de dépôt du plus ancien dossier à celle du plus récent.
    ends = []
    for order in ("ASC", "DESC"):
        res = await dn.gql(Q_RANGE, {"n": demarche, "order": order})
        ends.append(datetime.fromisoformat(res.data["demarche"]["dossiers"]["nodes"][0]["dateDepot"]))
    start, end = min(ends), max(ends)
    step = (end - start) / flux
    # Le 1er flux part de loin (un dossier est créé avant d'être déposé) ; les autres découpent la période.
    bounds = [(start - timedelta(days=400)).isoformat()] + [(start + step * k).isoformat() for k in range(1, flux)]

    firsts = await asyncio.gather(*(page(dn, demarche, b, None) for b in bounds))
    first_nums = [c["nodes"][0]["number"] if c["nodes"] else None for c in firsts]

    async def stream(k: int) -> dict:
        t0 = time.perf_counter()
        limit = next((f for f in first_nums[k + 1:] if f is not None), None)
        conn, pages, kept = firsts[k], 1, {}
        while True:
            stop = False
            for node in conn["nodes"]:
                if limit is not None and node["number"] >= limit:
                    stop = True
                    break
                kept[node["number"]] = sorted(l["id"] for l in node["labels"])
            if stop or not conn["pageInfo"]["hasNextPage"]:
                break
            conn = await page(dn, demarche, bounds[k], conn["pageInfo"]["endCursor"])
            pages += 1
        return {"flux": k, "depuis": bounds[k], "dossiers": len(kept), "pages": pages,
                "ms": round((time.perf_counter() - t0) * 1000, 1), "labels": kept}

    parts = await asyncio.gather(*(stream(k) for k in range(flux)))
    merged = {num: labels for p in parts for num, labels in p["labels"].items()}
    return merged, parts


async def main() -> None:
    demarche = env_int("DN_DEMARCHE")
    flux = max(2, min(env_int("DN_FLUX", required=False, default=6), 10))
    dn = DN()
    out: dict = {"flux": flux}
    try:
        print("Référence : lecture séquentielle")
        seq = await read_all(dn, demarche, 100)
        print(f"   {seq['dossiers']} dossiers en {seq['ms']} ms")

        print(f"\nA. Découpage par date de création ({flux} flux)")
        t0 = time.perf_counter()
        merged, parts = await fan_out(dn, demarche, flux)
        fan_ms = round((time.perf_counter() - t0) * 1000, 1)
        for p in parts:
            print(f"   flux {p['flux']}  {p['dossiers']:>6} dossiers, {p['pages']:>3} pages, {p['ms']} ms")
        same = merged == seq["labels"]
        print(f"   total {len(merged)} dossiers en {fan_ms} ms (gain ×{round(seq['ms'] / fan_ms, 2)})")
        print(f"   Cohérence avec la référence : {'identique ✅' if same else 'DIFFÉRENT ⚠️'}")
        if not same:
            print(f"   manquants : {sorted(set(seq['labels']) - set(merged))[:20]}")
        out["decoupage"] = {"ms": fan_ms, "coherent": same, "reference_ms": seq["ms"],
                            "par_flux": [{k: v for k, v in p.items() if k != "labels"} for p in parts]}

        print("\nB. Rafraîchissement ciblé par alias dossier(number:)")
        numbers = list(seq["labels"])
        out["cible"] = []
        for size in (25, 50, 100):
            sample = random.sample(numbers, min(size, len(numbers)))
            res = await dn.gql(build_multi(len(sample)), {f"n{k}": n for k, n in enumerate(sample)})
            got = sum(1 for k in range(len(sample)) if (res.data or {}).get(f"d{k}"))
            print(f"   {len(sample):>3} dossiers → {got} lus en {res.ms} ms"
                  + (f"  ⚠️ {res.errors[:1]}" if res.errors else ""))
            out["cible"].append({"taille": len(sample), "lus": got, "ms": res.ms, "errors": res.errors})
            if res.errors:
                break
        save_result("dn_02b_lecture_rapide", out)
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
