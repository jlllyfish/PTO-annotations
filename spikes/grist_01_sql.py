"""Grist 01 — Endpoint /sql sur les tables d'OTP (lecture seule).

Vérifie :
- que /sql est disponible sur l'instance, avec paramètres liés (`args`) ;
- qu'une valeur malveillante passée en paramètre ne change pas la requête ;
- la jointure dossiers ↔ champs ↔ annotations sur `dossier_number` et son temps de réponse ;
- la présence des colonnes de labels écrites par OTP (label_names, labels_json).
"""

import asyncio

from common import Grist, env_int, safe_table, save_result


async def main() -> None:
    n = env_int("DN_DEMARCHE")
    grist = Grist()
    out: dict = {"requetes": []}

    async def run(name: str, sql: str, args: list | None = None) -> list:
        status, ms, body = await grist.sql(sql, args)
        rows = body.get("records", []) if isinstance(body, dict) else []
        ok = status == 200
        print(f"   {name:<40} HTTP {status} — {len(rows)} ligne(s), {ms} ms" + ("" if ok else f"  ⚠️ {body}"))
        out["requetes"].append({"nom": name, "status": status, "ms": ms, "lignes": len(rows),
                                "erreur": None if ok else body})
        return rows

    try:
        tables = await grist.table_ids()
        otp = [t for t in tables if t.startswith(f"Demarche_{n}_")]
        print(f"Tables OTP trouvées pour la démarche {n} : {otp or 'aucune'}")
        out["tables_otp"] = otp
        dossiers = safe_table(f"Demarche_{n}_dossiers", tables)

        print("\nRequêtes")
        await run("comptage dossiers", f"SELECT COUNT(*) AS n FROM {dossiers}")
        rows = await run("colonnes labels OTP",
                         f"SELECT dossier_number, state, label_names, labels_json FROM {dossiers} LIMIT 5")
        for r in rows[:3]:
            print(f"     {r['fields']}")

        state_rows = await run("filtre paramétré (state = ?)",
                               f"SELECT dossier_number FROM {dossiers} WHERE state = ? LIMIT 50", ["en_instruction"])
        evil = await run("injection en paramètre (doit rendre 0)",
                         f"SELECT dossier_number FROM {dossiers} WHERE state = ?", ["x' OR '1'='1"])
        out["injection_neutralisee"] = len(evil) == 0

        await run("LIKE paramétré (label_names)",
                  f"SELECT COUNT(*) AS n FROM {dossiers} WHERE label_names LIKE ?", ["%Urgent%"])

        for suffix in ("champs", "annotations"):
            name = f"Demarche_{n}_{suffix}"
            if name in tables:
                other = safe_table(name, tables)
                await run(f"jointure dossiers ↔ {suffix}",
                          f"SELECT COUNT(*) AS n FROM {dossiers} d "
                          f"JOIN {other} x ON x.dossier_number = d.dossier_number")

        # Une requête d'écriture doit être refusée par /sql (lecture seule attendue).
        # On vise une table inexistante : même si elle passait, elle ne toucherait rien.
        await run("écriture refusée ? (table fictive)", 'DELETE FROM "Table_inexistante_spike" WHERE 1=0')

        print(f"\nInjection neutralisée : {'oui ✅' if out['injection_neutralisee'] else 'NON ⚠️'}")
        save_result("grist_01_sql", out)
    finally:
        await grist.close()


if __name__ == "__main__":
    asyncio.run(main())
