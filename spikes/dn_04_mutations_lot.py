"""DN 04 — Mutations groupées par alias (ÉCRIT dans DN, puis remet tout en état).

Mesure / vérifie sur les dossiers et labels de test :
1. lots de tailles croissantes (ajout puis retrait) : temps, erreurs, taille max acceptée ;
2. idempotence : ajouter deux fois le même label, retirer deux fois ;
3. erreur partielle : un lot contenant un labelId invalide applique-t-il quand même le reste ?

N'utilise que les couples (dossier, label) où le label est ABSENT au départ :
ajouter puis retirer ramène donc chaque dossier à son état initial.

Lancer avec : python dn_04_mutations_lot.py --ecrire
"""

import asyncio

from common import DN, env_list, require_flag, save_result
from dn_labels import apply_batch, get_dossier

SIZES = [1, 5, 10, 25, 50, 100]
FAKE_LABEL_ID = "TGFiZWwtOTk5OTk5OTk5"  # « Label-999999999 » encodé, n'existe pas


async def main() -> None:
    require_flag("--ecrire", "ajoute puis retire des labels sur les dossiers de test")
    numbers = [int(n) for n in env_list("DN_TEST_DOSSIERS")]
    label_ids = env_list("DN_TEST_LABEL_IDS")
    dn = DN()
    out: dict = {"lots": []}
    try:
        dossiers = [await get_dossier(dn, n) for n in numbers]
        initial = {d["id"]: {l["id"] for l in d["labels"]} for d in dossiers}
        pairs = [(d["id"], l) for d in dossiers for l in label_ids if l not in initial[d["id"]]]
        print(f"{len(pairs)} couple(s) (dossier, label) utilisables")
        if not pairs:
            raise SystemExit("Aucun couple utilisable : ajoutez des dossiers ou des labels de test.")

        # 1. Tailles de lot
        print("\n1. Lots par alias")
        for size in [s for s in SIZES if s <= len(pairs)] or [len(pairs)]:
            batch = pairs[:size]
            add, add_ops = await apply_batch(dn, "ajouter", batch)
            rm, rm_ops = await apply_batch(dn, "retirer", batch)
            add_ok = sum(o["ok"] for o in add_ops)
            rm_ok = sum(o["ok"] for o in rm_ops)
            print(f"   {size:>3} ops — ajout {add_ok}/{size} en {add.ms} ms, retrait {rm_ok}/{size} en {rm.ms} ms"
                  + (f"  ⚠️ {add.errors or rm.errors}" if add.errors or rm.errors else ""))
            out["lots"].append({
                "taille": size,
                "ajout": {"ms": add.ms, "ok": add_ok, "status": add.status, "errors": add.errors, "headers": add.headers},
                "retrait": {"ms": rm.ms, "ok": rm_ok, "status": rm.status, "errors": rm.errors},
            })
            if add.errors or rm.errors:
                break  # taille max atteinte : inutile d'insister

        # 2. Idempotence
        print("\n2. Idempotence")
        one = [pairs[0]]
        _, a1 = await apply_batch(dn, "ajouter", one)
        _, a2 = await apply_batch(dn, "ajouter", one)
        _, r1 = await apply_batch(dn, "retirer", one)
        _, r2 = await apply_batch(dn, "retirer", one)
        for name, op in (("ajout 1", a1), ("ajout 2 (déjà présent)", a2), ("retrait 1", r1), ("retrait 2 (déjà absent)", r2)):
            print(f"   {name:<26} ok={op[0]['ok']} erreurs={op[0]['erreurs']}")
        out["idempotence"] = {"ajout_1": a1[0], "ajout_2": a2[0], "retrait_1": r1[0], "retrait_2": r2[0]}

        # 3. Erreur partielle
        print("\n3. Lot avec un labelId invalide")
        mixed = [pairs[0], (pairs[0][0], FAKE_LABEL_ID)]
        res, ops = await apply_batch(dn, "ajouter", mixed)
        print(f"   op valide appliquée : {ops[0]['label_present_apres'] or ops[0]['ok']} ; "
              f"op invalide : ok={ops[1]['ok']} {ops[1]['erreurs']} ; erreurs globales : {res.errors}")
        out["erreur_partielle"] = {"ops": ops, "errors": res.errors, "status": res.status}
        await apply_batch(dn, "retirer", [pairs[0]])

        # Contrôle final : retour à l'état initial
        final = [await get_dossier(dn, n) for n in numbers]
        restored = all({l["id"] for l in d["labels"]} == initial[d["id"]] for d in final)
        print(f"\nRetour à l'état initial : {'OK ✅' if restored else 'À VÉRIFIER ⚠️'}")
        out["etat_restaure"] = restored
        save_result("dn_04_mutations_lot", out)
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
