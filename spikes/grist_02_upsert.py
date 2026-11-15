"""Grist 02 — Upsert natif en masse (ÉCRIT dans Grist, sur une table temporaire).

Crée une table `LBL_Spike`, y envoie N lignes avec `PUT /records` + `require`
(clé : dossier_number + label_id), renvoie les mêmes lignes modifiées et vérifie
qu'elles sont mises à jour sans doublon. Supprime la table à la fin (sauf --garder).

Lancer avec : python grist_02_upsert.py --ecrire [--garder]
"""

import asyncio
import sys

from common import Grist, env_int, require_flag, save_result

TABLE = "LBL_Spike"
BATCH = 500


async def put_records(grist: Grist, records: list[dict]) -> tuple[float, list]:
    total_ms, errors = 0.0, []
    for i in range(0, len(records), BATCH):
        status, ms, body = await grist.request(
            "PUT", f"/tables/{TABLE}/records", json={"records": records[i:i + BATCH]}
        )
        total_ms += ms
        if status != 200:
            errors.append({"status": status, "body": body})
    return round(total_ms, 1), errors


async def count(grist: Grist) -> int:
    status, _, body = await grist.sql(f'SELECT COUNT(*) AS n FROM "{TABLE}"')
    return body["records"][0]["fields"]["n"] if status == 200 else -1


async def main() -> None:
    require_flag("--ecrire", f"crée puis supprime une table temporaire {TABLE} dans le document Grist")
    n = env_int("GRIST_UPSERT_LIGNES", required=False, default=2000)
    grist = Grist()
    out: dict = {"lignes": n}
    created = False
    try:
        if TABLE in await grist.table_ids():
            raise SystemExit(f"La table {TABLE} existe déjà : supprimez-la avant de relancer.")
        created = True  # à partir d'ici, la table est la nôtre (même si la création échoue)
        status, _, body = await grist.request("POST", "/tables", json={"tables": [{
            "id": TABLE,
            "columns": [
                {"id": "dossier_number", "fields": {"type": "Int"}},
                {"id": "label_id", "fields": {"type": "Text"}},
                {"id": "statut", "fields": {"type": "Text"}},
            ],
        }]})
        if status != 200:
            raise SystemExit(f"Création de la table impossible : {status} {body}")

        def rows(statut: str) -> list[dict]:
            return [{"require": {"dossier_number": i, "label_id": f"L{i % 7}"}, "fields": {"statut": statut}}
                    for i in range(1, n + 1)]

        ms1, err1 = await put_records(grist, rows("en_attente"))
        c1 = await count(grist)
        print(f"1er upsert (création) : {n} lignes en {ms1} ms → {c1} lignes en table {err1 or ''}")
        ms2, err2 = await put_records(grist, rows("applique"))
        c2 = await count(grist)
        print(f"2e upsert (mise à jour) : {n} lignes en {ms2} ms → {c2} lignes en table {err2 or ''}")

        _, _, body = await grist.sql(f'SELECT COUNT(*) AS n FROM "{TABLE}" WHERE statut = ?', ["applique"])
        updated = body["records"][0]["fields"]["n"]
        no_dup = c1 == c2 == n and updated == n
        print(f"Sans doublon et tout mis à jour : {'oui ✅' if no_dup else 'NON ⚠️'}")
        out.update({"creation_ms": ms1, "maj_ms": ms2, "lignes_apres_creation": c1,
                    "lignes_apres_maj": c2, "lignes_maj": updated, "sans_doublon": no_dup,
                    "erreurs": err1 + err2})
        save_result("grist_02_upsert", out)
    finally:
        if created and "--garder" not in sys.argv and TABLE in await grist.table_ids():
            status, _, _ = await grist.request("POST", "/apply", json=[["RemoveTable", TABLE]])
            print(f"Table temporaire supprimée : {'oui' if status == 200 else f'non (HTTP {status})'}")
        await grist.close()


if __name__ == "__main__":
    asyncio.run(main())
