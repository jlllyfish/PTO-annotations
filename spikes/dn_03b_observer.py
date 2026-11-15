"""DN 03b — Observer un dossier pendant qu'on modifie ses labels À LA MAIN dans DN (lecture seule).

Affiche dateDerniereModification et les labels du 1er dossier de DN_TEST_DOSSIERS,
puis les relit à chaque appui sur Entrée. Entre deux lectures, ajoutez ou retirez
un label dans l'interface DN. Tapez q puis Entrée pour finir.
"""

import asyncio

from common import DN, env_list, save_result
from dn_labels import get_dossier


async def main() -> None:
    number = int(env_list("DN_TEST_DOSSIERS")[0])
    dn = DN()
    history = []
    try:
        previous = None
        while True:
            d = await get_dossier(dn, number)
            labels = sorted(l["name"] for l in d["labels"])
            date = d["dateDerniereModification"]
            change = "" if previous is None else ("  ← date MODIFIÉE" if date != previous else "  ← date inchangée")
            print(f"Dossier {number} | dateDerniereModification {date} | labels {labels or '[]'}{change}")
            history.append({"date": date, "labels": labels})
            previous = date
            action = await asyncio.to_thread(input, "Modifiez un label dans DN puis Entrée (q pour finir) : ")
            if action.strip().lower() == "q":
                break
        save_result("dn_03b_observer", {"dossier": number, "lectures": history})
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
