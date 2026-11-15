"""DN 05 — Comportement sous rafale (lecture seule, volontairement modéré).

Envoie DN_RAFALE_REQUETES requêtes légères (défaut 60) avec DN_RAFALE_CONCURRENCE
requêtes simultanées (défaut 5) et relève codes HTTP, latences et en-têtes de limite.
S'arrête au premier HTTP 429 pour ne pas insister.

Lancer avec : python dn_05_debit.py --rafale
"""

import asyncio
import statistics
import time
from collections import Counter

from common import DN, env_int, require_flag, save_result

QUERY = "query Ping($n: Int!) { demarche(number: $n) { number } }"


async def main() -> None:
    require_flag("--rafale", "envoie une rafale de requêtes vers l'API DN")
    demarche = env_int("DN_DEMARCHE")
    total = min(env_int("DN_RAFALE_REQUETES", required=False, default=60), 300)
    concurrency = min(env_int("DN_RAFALE_CONCURRENCE", required=False, default=5), 20)
    dn = DN()
    sem = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()
    results = []

    async def one() -> None:
        if stop.is_set():
            return
        async with sem:
            if stop.is_set():
                return
            res = await dn.gql(QUERY, {"n": demarche})
            results.append(res)
            if res.status == 429:
                stop.set()

    try:
        start = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(total)))
        elapsed = time.perf_counter() - start
        lat = sorted(r.ms for r in results)
        codes = Counter(r.status for r in results)
        first_429 = next((r for r in results if r.status == 429), None)
        print(f"{len(results)} requêtes en {elapsed:.1f} s ({len(results) / elapsed:.1f} req/s)")
        print(f"Codes HTTP : {dict(codes)}")
        print(f"Latence p50 {statistics.median(lat):.0f} ms, p95 {lat[int(len(lat) * 0.95) - 1]:.0f} ms")
        headers = first_429.headers if first_429 else results[-1].headers
        print(f"En-têtes de limite relevés : {headers or 'aucun'}")
        save_result("dn_05_debit", {
            "requetes": len(results),
            "concurrence": concurrency,
            "duree_s": round(elapsed, 2),
            "req_par_s": round(len(results) / elapsed, 2),
            "codes": dict(codes),
            "p50_ms": statistics.median(lat),
            "p95_ms": lat[int(len(lat) * 0.95) - 1],
            "headers": headers,
            "premier_429_apres": results.index(first_429) + 1 if first_429 else None,
        })
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
