"""ANN 02 — Écriture des annotations privées (ÉCRIT dans DN, puis remet tout en état).

N'agit que sur DN_TEST_DOSSIERS × DN_TEST_ANNOTATION_IDS, et seulement pour des annotations de type
texte, zone de texte ou case à cocher (valeurs restaurables à l'identique).

Questions :
1. `dossierModifierAnnotations` : plusieurs annotations d'un dossier en un appel ? Temps ?
2. Quel identifiant accepter : id du champ, id du descripteur (`champDescriptorId`) ?
3. Effet sur `updatedAt`, `dateDerniereModificationAnnotations`, `dateDerniereModification`, `updatedSince`
   (→ détection « annotation modifiée dans DN depuis la synchro »).
4. Réécrire la valeur identique modifie-t-il `updatedAt` ? (sinon : inutile d'envoyer, on compare)
5. Lots par alias sur plusieurs dossiers : tailles 1 → 50, erreurs rattachées à l'alias.
6. Erreurs : mauvais type de valeur ; annotation inconnue mêlée à une valide (le reste passe-t-il ?).
7. Le texte vide `""` est-il accepté (utile pour restaurer) ?
8. (optionnel) instructeur hors du groupe du dossier : refusé ?

Lancer avec : python ann_02_mutations.py --ecrire
"""

import asyncio
from datetime import datetime, timedelta, timezone

from common import DN, env, env_int, env_list, require_flag, save_result
from dn_annotations import Q_CATALOGUE, Q_DEPUIS, annotation, envoyer_lot, get_dossier

CLES = {"TextChampDescriptor": "text", "TextareaChampDescriptor": "textarea", "CheckboxChampDescriptor": "checkbox",
        "DropDownListChampDescriptor": "dropDownList"}
OPTIONS: dict[str, list[str]] = {}  # options des listes déroulantes, par id de descripteur
FAUX_ID = "Q2hhbXAtOTk5OTk5OTk5"  # « Champ-999999999 », n'existe pas
SIZES = [1, 5, 10, 25, 50]


def valeur_actuelle(a: dict, cle: str):
    if cle == "checkbox":
        return bool(a.get("coche"))
    if cle == "dropDownList":
        return a.get("choix") or ""
    return a.get("texte") or ""


def valeur_test(a: dict, cle: str, marque: str):
    if cle == "checkbox":
        return not bool(a.get("coche"))
    if cle == "dropDownList":
        return next(o for o in OPTIONS[a["champDescriptorId"]] if o != valeur_actuelle(a, cle))
    return f"{valeur_actuelle(a, cle)} [{marque}]".strip()


async def main() -> None:
    require_flag("--ecrire", "modifie puis restaure des annotations privées sur les dossiers de test")
    demarche = env_int("DN_DEMARCHE")
    numeros = [int(n) for n in env_list("DN_TEST_DOSSIERS")]
    ids_ann = env_list("DN_TEST_ANNOTATION_IDS")
    email = (env("DN_TEST_INSTRUCTEUR_EMAIL") or "").strip().lower()
    email_hors = (env("DN_TEST_INSTRUCTEUR_HORS_GROUPE_EMAIL", required=False) or "").strip().lower()
    marque = "PTO-test " + datetime.now().strftime("%H:%M:%S")
    dn = DN()
    out: dict = {}
    try:
        cat = await dn.gql(Q_CATALOGUE, {"n": demarche})
        if not cat.ok:
            raise SystemExit(f"Catalogue illisible : {cat.errors}")
        d = cat.data["demarche"]
        types = {a["id"]: a["__typename"] for a in d["activeRevision"]["annotationDescriptors"]}
        OPTIONS.update({a["id"]: a.get("options") or [] for a in d["activeRevision"]["annotationDescriptors"]})
        instr = {i["email"].lower(): i["id"] for g in d["groupeInstructeurs"] for i in g["instructeurs"]}
        if email not in instr:
            raise SystemExit("DN_TEST_INSTRUCTEUR_EMAIL n'est instructeur d'aucun groupe de la démarche")
        instructeur_id = instr[email]

        dossiers = [await get_dossier(dn, n) for n in numeros]
        for ident in ids_ann:
            if CLES.get(types.get(ident, "")) is None:
                raise SystemExit(f"Annotation {ident} : type {types.get(ident)} non testé "
                                 "(texte, zone de texte, case à cocher ou liste déroulante)")
        cibles = []  # (dossier, champ_id, descripteur_id, clé)
        absentes = []  # (dossier, descripteur_id) : annotation de la démarche absente du dossier
        for dos in dossiers:
            for ident in ids_ann:
                a = annotation(dos, ident)
                if a is None:
                    absentes.append((dos, ident))
                    continue
                cibles.append((dos, a["id"], a["champDescriptorId"], CLES[types[ident]]))
        if absentes:
            print(f"⚠️ {len(absentes)} couple(s) (dossier, annotation) absents du dossier : testés à part (étape 9)")
        dossiers = [dos for dos in dossiers if any(c[0]["id"] == dos["id"] for c in cibles)]
        if not dossiers:
            raise SystemExit("Aucun dossier ne porte les annotations choisies")
        initial = {(dos["id"], cid): valeur_actuelle(annotation(dos, cid), cle) for dos, cid, _, cle in cibles}
        print(f"{len(dossiers)} dossier(s), {len(ids_ann)} annotation(s) par dossier, instructeur trouvé")

        def entree(dossier_id: str, valeurs: list[tuple[str, str, object]], instructeur: str = instructeur_id):
            return {"dossierId": dossier_id, "instructeurId": instructeur,
                    "annotations": [{"id": i, "value": {cle: v}} for i, cle, v in valeurs]}

        async def restaurer(doss: list[dict]) -> None:
            inputs = []
            for dos in doss:
                vals = [(cid, cle, initial[(dos["id"], cid)]) for dd, cid, _, cle in cibles if dd["id"] == dos["id"]]
                inputs.append(entree(dos["id"], vals))
            for k in range(0, len(inputs), 50):
                await envoyer_lot(dn, inputs[k : k + 50])

        d0 = dossiers[0]
        c0 = [c for c in cibles if c[0]["id"] == d0["id"]]

        # 1 + 3. Un dossier, toutes ses annotations, id du champ
        print("\n1. Un dossier, toutes ses annotations en un appel (id du champ)")
        avant = await get_dossier(dn, d0["number"])
        t0 = datetime.now(timezone.utc) - timedelta(seconds=5)
        res, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, valeur_test(annotation(avant, cid), cle, marque))
                                                            for _, cid, _, cle in c0])])
        apres = await get_dossier(dn, d0["number"])
        print(f"   ok={ops[0]['ok']} en {res.ms} ms {ops[0]['erreurs'] or ''}")
        dates = {k: (avant[k], apres[k]) for k in ("dateDerniereModification", "dateDerniereModificationAnnotations")}
        maj = {cid: (annotation(avant, cid)["updatedAt"], annotation(apres, cid)["updatedAt"]) for _, cid, _, _ in c0}
        await asyncio.sleep(2)
        depuis = await dn.gql(Q_DEPUIS, {"n": demarche, "since": t0.isoformat()})
        vu = any(int(x["number"]) == d0["number"] for x in (depuis.data or {}).get("demarche", {}).get("dossiers", {}).get("nodes", []))
        print("3. Effet sur les dates")
        for k, (a, b) in dates.items():
            print(f"   {k:<38} {'modifiée' if a != b else 'INCHANGÉE'}")
        print(f"   updatedAt de chaque annotation          {'modifié' if all(a != b for a, b in maj.values()) else 'PAS TOUJOURS modifié'}")
        print(f"   dossier vu par updatedSince              {'oui' if vu else 'NON'}")
        out["un_dossier"] = {"ms": res.ms, "op": ops[0], "dates": dates, "updatedAt": maj, "vu_updated_since": vu}

        # 4. Valeur identique
        print("\n4. Réécriture de la valeur identique")
        avant = await get_dossier(dn, d0["number"])
        _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, valeur_actuelle(annotation(avant, cid), cle))
                                                          for _, cid, _, cle in c0])])
        apres = await get_dossier(dn, d0["number"])
        change = {k: avant[k] != apres[k] for k in ("dateDerniereModification", "dateDerniereModificationAnnotations")}
        change["updatedAt"] = any(annotation(avant, cid)["updatedAt"] != annotation(apres, cid)["updatedAt"] for _, cid, _, _ in c0)
        print(f"   ok={ops[0]['ok']} ; dates modifiées : {change}")
        out["valeur_identique"] = {"op": ops[0], "dates_modifiees": change}
        await restaurer([d0])

        # 2. Id du descripteur
        print("\n2. Même écriture avec champDescriptorId")
        if all(cid == did for _, cid, did, _ in c0):
            print("   id du champ = champDescriptorId : rien à tester")
            out["id_descripteur"] = "identique"
        else:
            avant = await get_dossier(dn, d0["number"])
            _, ops = await envoyer_lot(dn, [entree(d0["id"], [(did, cle, valeur_test(annotation(avant, cid), cle, marque))
                                                              for _, cid, did, cle in c0])])
            print(f"   ok={ops[0]['ok']} {ops[0]['erreurs'] or ''}")
            out["id_descripteur"] = ops[0]
            await restaurer([d0])

        # 5. Lots par alias
        print("\n5. Lots par alias (un dossier par alias)")
        out["lots"] = []
        for size in sorted({s for s in SIZES if s <= len(dossiers)} | {min(len(dossiers), 50)}):
            lot = dossiers[:size]
            inputs = []
            for dos in lot:
                vals = [(cid, cle, valeur_test(annotation(dos, cid), cle, marque)) for dd, cid, _, cle in cibles if dd["id"] == dos["id"]]
                inputs.append(entree(dos["id"], vals))
            res, ops = await envoyer_lot(dn, inputs)
            ok = sum(o["ok"] for o in ops)
            print(f"   {size:>3} dossiers — {ok}/{size} en {res.ms} ms" + (f"  ⚠️ {res.errors}" if res.errors else ""))
            out["lots"].append({"taille": size, "ms": res.ms, "ok": ok, "status": res.status, "errors": res.errors})
            await restaurer(lot)
            if res.errors:
                break

        # 6. Erreurs
        print("\n6. Erreurs")
        _, cid, _, cle = c0[0]
        mauvais = "checkbox" if cle != "checkbox" else "text"
        mauvaise_valeur = True if mauvais == "checkbox" else "x"
        _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, mauvais, mauvaise_valeur)])])
        print(f"   mauvais type         : ok={ops[0]['ok']} {ops[0]['erreurs']}")
        out["mauvais_type"] = ops[0]
        avant = await get_dossier(dn, d0["number"])
        _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, valeur_test(annotation(avant, cid), cle, marque)),
                                                          (FAUX_ID, "text", "x")])])
        apres = await get_dossier(dn, d0["number"])
        applique = valeur_actuelle(annotation(apres, cid), cle) != valeur_actuelle(annotation(avant, cid), cle)
        print(f"   annotation inconnue mêlée à une valide (même dossier) : ok={ops[0]['ok']} ; "
              f"valide appliquée={applique} ; {ops[0]['erreurs']}")
        out["meme_dossier_partiel"] = {"op": ops[0], "valide_appliquee": applique}
        await restaurer([d0])
        if len(dossiers) > 1:
            d1 = dossiers[1]
            c1 = [c for c in cibles if c[0]["id"] == d1["id"]]
            res, ops = await envoyer_lot(dn, [entree(d0["id"], [(FAUX_ID, "text", "x")]),
                                              entree(d1["id"], [(cid, cle, valeur_test(annotation(d1, cid), cle, marque)) for _, cid, _, cle in c1])])
            print(f"   lot : alias en erreur + alias valide → valide ok={ops[1]['ok']} ; erreur={ops[0]['erreurs']}")
            out["lot_partiel"] = {"ops": ops, "errors": res.errors}
            await restaurer([d1])

        # 7. Texte vide
        textes = [c for c in c0 if c[3] in ("text", "textarea")]
        if textes:
            _, cid, _, cle = textes[0]
            _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, "")])])
            print(f"\n7. Texte vide accepté : {ops[0]['ok']} {ops[0]['erreurs'] or ''}")
            out["texte_vide"] = ops[0]
            await restaurer([d0])
        listes = [c for c in c0 if c[3] == "dropDownList"]
        if listes:
            _, cid, _, cle = listes[0]
            _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, "")])])
            print(f"   Liste déroulante vidée par \"\" : {ops[0]['ok']} {ops[0]['erreurs'] or ''}")
            out["liste_vide"] = ops[0]
            await restaurer([d0])

        # 8. Instructeur hors groupe
        if email_hors:
            if email_hors not in instr:
                print("\n8. DN_TEST_INSTRUCTEUR_HORS_GROUPE_EMAIL introuvable dans la démarche : ignoré")
            else:
                _, cid, _, cle = c0[0]
                _, ops = await envoyer_lot(dn, [entree(d0["id"], [(cid, cle, valeur_test(annotation(d0, cid), cle, marque))], instr[email_hors])])
                print(f"\n8. Instructeur hors groupe : ok={ops[0]['ok']} {ops[0]['erreurs']}")
                out["instructeur_hors_groupe"] = ops[0]
                await restaurer([d0])

        # 9. Annotation de la démarche absente du dossier (dossier déposé sur une révision antérieure ?)
        if absentes:
            dos, ident = absentes[0]
            cle = CLES[types[ident]]
            val = OPTIONS[ident][0] if cle == "dropDownList" else (True if cle == "checkbox" else f"[{marque}]")
            _, ops = await envoyer_lot(dn, [entree(dos["id"], [(ident, cle, val)])])
            apres = await get_dossier(dn, dos["number"])
            cree = annotation(apres, ident) is not None
            print(f"\n9. Écriture sur une annotation absente du dossier {dos['number']} : ok={ops[0]['ok']} "
                  f"; annotation apparue={cree} {ops[0]['erreurs'] or ''}")
            out["annotation_absente"] = {"op": ops[0], "apparue": cree}
            if cree:
                vide = False if cle == "checkbox" else ""
                _, ops = await envoyer_lot(dn, [entree(dos["id"], [(ident, cle, vide)])])
                print(f"   remise à vide : ok={ops[0]['ok']} {ops[0]['erreurs'] or ''}")

        # Contrôle final
        final = [await get_dossier(dn, dos["number"]) for dos in dossiers]
        restaure = all(valeur_actuelle(annotation(f, cid), cle) == initial[(f["id"], cid)]
                       for f in final for dd, cid, _, cle in cibles if dd["id"] == f["id"])
        print(f"\nRetour à l'état initial : {'OK ✅' if restaure else 'À VÉRIFIER ⚠️'}")
        out["etat_restaure"] = restaure
        save_result("ann_02_mutations", out)
    except BaseException:
        if "restaurer" in locals() and "dossiers" in locals():
            print("\nInterruption : tentative de restauration des valeurs initiales…")
            await restaurer(dossiers)
        raise
    finally:
        await dn.close()


if __name__ == "__main__":
    asyncio.run(main())
