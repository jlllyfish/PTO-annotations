"""DN 03 — Un changement de label est-il visible via `updatedSince` ? (ÉCRIT dans DN)

Sur UN dossier de test : ajoute un label absent, vérifie si `dateDerniereModification`
bouge et si le dossier remonte dans `dossiers(updatedSince: …)`, puis retire le label
pour revenir à l'état initial.

Lancer avec : python dn_03_updated_since.py --ecrire
"""

import asyncio
from datetime import datetime, timedelta, timezone

from common import DN, env_int, env_list, require_flag, save_result
from dn_labels import apply_batch, get_dossier

UPDATED_SINCE = """
query Updated($n: Int!, $since: ISO8601DateTime!, $after: String) {
  demarche(number: $n) {
    dossiers(first: 100, after: $after, updatedSince: $since) {
      pageInfo { hasNextPage endCursor }
      nodes { number }
    }
  }
}
"""


async def appears_in_updated_since(dn: DN, demarche: int, since: str, number: int) -> bool:
    after = None
    for _ in range(50):  # garde-fou
        res = await dn.gql(UPDATED_SINCE, {"n": demarche, "since": since, "after": after})
        if not res.ok:
            raise RuntimeError(f"updatedSince : {res.status} {res.errors}")
        conn = res.data["demarche"]["dossiers"]
        if any(n["number"] == number for n in conn["nodes"]):
            return True
        if not conn["pageInfo"]["hasNextPage"]:
            return False
        after = conn["pageInfo"]["endCursor"]
    return False


async def main() -> None:
    require_flag("--ecrire", "ajoute puis retire un label sur un dossier de test")
    demarche = env_int("DN_DEMARCHE")
    number = int(env_list("DN_TEST_DOSSIERS")[0])
    label_ids = env_list("DN_TEST_LABEL_IDS")
    dn = DN()
    try:
        before = await get_dossier(dn, number)
        present = {l["id"] for l in before["labels"]}
        label = next((l for l in label_ids if l not in present), None)
        if not label:
            raise SystemExit("Tous les labels de test sont déjà sur ce dossier : retirez-en un ou ajoutez un label de test.")

        since = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        print(f"Dossier {number} — dateDerniereModification avant : {before['dateDerniereModification']}")
        await asyncio.sleep(2)

        res, ops = await apply_batch(dn, "ajouter", [(before["id"], label)])
        print(f"Ajout du label : {'OK' if ops[0]['ok'] else ops[0]['erreurs'] or res.errors}")
        await asyncio.sleep(3)

        after = await get_dossier(dn, number)
        date_changed = after["dateDerniereModification"] != before["dateDerniereModification"]
        visible = await appears_in_updated_since(dn, demarche, since, number)
        print(f"dateDerniereModification après : {after['dateDerniereModification']} "
              f"→ {'modifiée' if date_changed else 'INCHANGÉE'}")
        print(f"Remonte dans updatedSince : {'oui' if visible else 'NON'}")

        _, rm = await apply_batch(dn, "retirer", [(before["id"], label)])
        restored = await get_dossier(dn, number)
        ok_restore = {l["id"] for l in restored["labels"]} == present
        print(f"Retour à l'état initial : {'OK ✅' if ok_restore else 'À VÉRIFIER ⚠️'}")

        save_result("dn_03_updated_since", {
            "dossier": number,
            "date_modifiee_par_label": date_changed,
            "visible_updated_since": visible,
            "ajout": ops[0],
            "retrait": rm[0],
            "etat_restaure": ok_restore,
        })
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
