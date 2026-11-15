"""Stockage, évaluation et application des règles (tables LBL_Regles et LBL_Regles_Traces).

« Ne pas refaire ce qu'un humain a défait » (verrou) : chaque dossier traité par une règle est mémorisé
dans LBL_Regles_Traces. Si, plus tard, le dossier remplit toujours la règle mais n'est plus dans l'état
qu'elle a produit, c'est qu'une personne est revenue dessus : la règle le laisse tranquille.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from pydantic import ValidationError

from ..config import DemarcheConfig
from ..dn.client import Action, DNClient
from ..grist.client import GristClient
from ..ops.service import BilanOps, executer
from ..sync.schema import assurer_schema, verifier_table_otp
from ..sync.service import ids_actuels
from .moteur import DefinitionRegle, RegleInvalide, champs_disponibles, compiler

REGLES = "LBL_Regles"
TRACES = "LBL_Regles_Traces"
MAX_PAR_EXECUTION = 500


def _numero(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


async def lister(grist: GristClient, d: DemarcheConfig, *, cle_schema: str) -> list[dict[str, Any]]:
    await assurer_schema(grist, cle_schema)
    rows = await grist.sql(
        f'SELECT * FROM "{REGLES}" WHERE demarche = ? ORDER BY id', [d.numero]  # noqa: S608  # nosec B608
    )
    out = []
    for r in rows:
        try:
            definition = DefinitionRegle.model_validate({
                "nom": r["nom"], "action": r["action"], "label_id": r["label_id"], "mode": r["mode"],
                "verrou": bool(r["verrou"]), "groupes": json.loads(r["conditions"] or "[]"),
            })
            erreur = None
        except (ValidationError, ValueError, TypeError) as exc:
            definition, erreur = None, f"Règle illisible : {str(exc)[:200]}"
        out.append({
            "id": r["id"], "definition": definition.model_dump() if definition else None, "erreur": erreur,
            "label": r.get("label"), "derniere_execution": r.get("derniere_execution"),
            "dernier_resultat": r.get("dernier_resultat"),
        })
    return out


async def _definition(grist: GristClient, d: DemarcheConfig, regle_id: int) -> DefinitionRegle:
    rows = await grist.sql(
        f'SELECT * FROM "{REGLES}" WHERE id = ? AND demarche = ?', [regle_id, d.numero]  # noqa: S608  # nosec B608
    )
    if not rows:
        raise RegleInvalide("règle introuvable")
    r = rows[0]
    return DefinitionRegle.model_validate({
        "nom": r["nom"], "action": r["action"], "label_id": r["label_id"], "mode": r["mode"],
        "verrou": bool(r["verrou"]), "groupes": json.loads(r["conditions"] or "[]"),
    })


async def enregistrer(dn: DNClient, grist: GristClient, d: DemarcheConfig, regle: DefinitionRegle, *,
                      cle_schema: str, regle_id: int | None = None) -> int:
    """Crée ou met à jour une règle après l'avoir validée contre le schéma et le catalogue DN."""
    await assurer_schema(grist, cle_schema)
    champs = await champs_disponibles(grist, d)
    compiler(d, regle, champs, time.time())  # lève RegleInvalide si un champ ou un opérateur ne convient pas
    label = next((l for l in await dn.catalogue(d.numero) if l.id == regle.label_id), None)
    if label is None:
        raise RegleInvalide("Ce label n'existe pas dans la démarche")
    champs_ligne = {
        "demarche": d.numero, "nom": regle.nom, "action": regle.action, "label_id": regle.label_id,
        "label": label.nom, "mode": regle.mode, "verrou": regle.verrou,
        "conditions": json.dumps([[c.model_dump() for c in g] for g in regle.groupes], ensure_ascii=False),
        "modifie_le": time.time(),
    }
    if regle_id is None:
        await grist.ajouter(REGLES, [champs_ligne])
        rows = await grist.sql(f'SELECT MAX(id) AS id FROM "{REGLES}" WHERE demarche = ?', [d.numero])  # noqa: S608  # nosec B608
        return int(rows[0]["id"])
    await _definition(grist, d, regle_id)  # vérifie que la règle appartient bien à cette démarche
    await grist.maj(REGLES, [{"id": regle_id, "fields": champs_ligne}])
    return regle_id


async def supprimer(grist: GristClient, d: DemarcheConfig, regle_id: int) -> None:
    await _definition(grist, d, regle_id)
    traces = await grist.sql(f'SELECT id FROM "{TRACES}" WHERE regle = ?', [regle_id])  # noqa: S608  # nosec B608
    if traces:
        await grist.supprimer(TRACES, [t["id"] for t in traces])
    await grist.supprimer(REGLES, [regle_id])


async def evaluer(grist: GristClient, d: DemarcheConfig, regle: DefinitionRegle, *, cle_schema: str,
                  regle_id: int | None = None, maintenant: float | None = None) -> dict[str, Any]:
    """Dossiers concernés par la règle, d'après l'état actuel de Grist (aucune écriture)."""
    await assurer_schema(grist, cle_schema)
    await verifier_table_otp(grist, d.table)
    champs = await champs_disponibles(grist, d)
    sql, args = compiler(d, regle, champs, maintenant or time.time())
    lignes = await grist.sql(sql, args)
    traces: set[str] = set()
    if regle_id is not None and regle.verrou:
        rows = await grist.sql(f'SELECT dossier_number FROM "{TRACES}" WHERE regle = ?', [regle_id])  # noqa: S608  # nosec B608
        traces = {_numero(r["dossier_number"]) for r in rows}
    a_faire, deja, verrouilles = [], [], []
    for l in lignes:
        num = _numero(l["dossier_number"])
        present = regle.label_id in (ids_actuels(l.get("labels_json")) or frozenset())
        dans_l_etat = present if regle.action == "ajouter" else not present
        if dans_l_etat:
            deja.append(num)
        elif num in traces:
            verrouilles.append(num)
        else:
            a_faire.append(num)
    return {
        "correspondants": len(lignes), "a_faire": len(a_faire), "deja": len(deja), "verrouilles": len(verrouilles),
        "numeros_a_faire": a_faire[:200], "numeros_verrouilles": verrouilles[:50], "_a_faire": a_faire,
    }


async def appliquer(dn: DNClient, grist: GristClient, d: DemarcheConfig, regle_id: int, *,
                    cle_schema: str, maintenant: float | None = None) -> BilanOps | None:
    """Exécute une règle enregistrée (500 dossiers au plus par passage) et mémorise les dossiers traités."""
    regle = await _definition(grist, d, regle_id)
    ev = await evaluer(grist, d, regle, cle_schema=cle_schema, regle_id=regle_id, maintenant=maintenant)
    numeros = [int(n) for n in ev["_a_faire"][:MAX_PAR_EXECUTION] if n.isdigit()]
    bilan = None
    if numeros:
        bilan = await executer(dn, grist, d, Action(regle.action), regle.label_id, numeros,
                               source=f"regle:{regle.nom}", cle_schema=cle_schema)
        traites = [n for n, st in bilan.statuts.items() if st in ("applique", "deja_applique")]
        if regle.verrou and traites:
            await grist.upsert(TRACES, [{"regle": regle_id, "dossier_number": str(n)} for n in traites],
                               ["regle", "dossier_number"])
    resume = (f"{bilan.appliques} appliqué(s), {bilan.deja} déjà, {bilan.erreurs + bilan.introuvables} erreur(s)"
              if bilan else "aucun dossier à traiter")
    if len(ev["_a_faire"]) > MAX_PAR_EXECUTION:
        resume += f" — {len(ev['_a_faire']) - MAX_PAR_EXECUTION} restant(s) au prochain passage"
    await grist.maj(REGLES, [{"id": regle_id,
                              "fields": {"derniere_execution": time.time(), "dernier_resultat": resume}}])
    return bilan


async def appliquer_regles_auto(dn: DNClient, grist: GristClient, d: DemarcheConfig, *,
                                cle_schema: str) -> list[dict[str, Any]]:
    """Tâche planifiée : exécute toutes les règles en mode automatique de la démarche."""
    resultats = []
    for r in await lister(grist, d, cle_schema=cle_schema):
        if not r["definition"] or r["definition"]["mode"] != "auto":
            continue
        try:
            bilan = await appliquer(dn, grist, d, r["id"], cle_schema=cle_schema)
            resultats.append({"regle": r["definition"]["nom"], "bilan": asdict(bilan) if bilan else None})
        except Exception as exc:  # une règle en échec n'empêche pas les suivantes
            resultats.append({"regle": r["definition"]["nom"], "erreur": str(exc)[:300]})
    return resultats
