"""Ajout / retrait de labels dans DN, unitaire ou en masse, avec file d'attente et journal (LBL_Operations).

Déroulé d'un envoi :
1. le label doit exister dans le catalogue DN de la démarche ;
2. lecture DN ciblée des dossiers : on écarte ceux introuvables ou d'une autre démarche, et ceux qui
   sont déjà dans l'état voulu (pas d'appel inutile, idempotence) ;
3. mutations par lots de 50 ; « déjà associé / pas associé » = déjà appliqué ;
4. mise à jour des colonnes de labels dans Grist (format OTP) d'après l'état renvoyé par DN ;
5. une ligne de journal par dossier.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ..config import DemarcheConfig
from ..dn.client import Action, DNClient, Label, Operation, Statut
from ..grist.client import GristClient
from ..sync.schema import assurer_schema, verifier_table_otp
from ..sync.service import champs_otp, ids_actuels, lignes_grist

JOURNAL = "LBL_Operations"
MAX_FILE = 2000
MSG_HORS = "Hors de vos groupes instructeurs"


class LabelInconnu(ValueError):
    pass


@dataclass
class BilanOps:
    action: str
    label: dict[str, str]
    appliques: int = 0
    deja: int = 0
    introuvables: int = 0
    hors_perimetre: int = 0
    erreurs: int = 0
    en_file: int = 0
    grist_maj: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)  # erreurs et introuvables (100 max)
    statuts: dict[int, str] = field(default_factory=dict)        # statut final de CHAQUE dossier

    def ajouter_detail(self, numero: int, statut: str, message: str | None) -> None:
        if statut != "applique" and len(self.details) < 100:
            self.details.append({"numero": numero, "statut": statut, "message": message})


def _besoin(labels: frozenset[str], action: Action, label_id: str) -> bool:
    return (label_id not in labels) if action == Action.AJOUTER else (label_id in labels)


def _apres(labels: frozenset[str], action: Action, label_id: str) -> frozenset[str]:
    return labels | {label_id} if action == Action.AJOUTER else labels - {label_id}


async def _label(dn: DNClient, d: DemarcheConfig, label_id: str) -> tuple[list[Label], Label]:
    catalogue = await dn.catalogue(d.numero)
    label = next((l for l in catalogue if l.id == label_id), None)
    if label is None:
        raise LabelInconnu("Ce label n'existe pas dans la démarche")
    return catalogue, label


def _vue_label(l: Label) -> dict[str, str]:
    return {"id": l.id, "nom": l.nom, "couleur": l.couleur}


def _hors(dossier, perimetre: frozenset[int] | None) -> bool:
    return perimetre is not None and dossier.groupe not in perimetre


async def apercu(dn: DNClient, d: DemarcheConfig, action: Action, label_id: str, numeros: Sequence[int],
                 perimetre: frozenset[int] | None = None) -> dict:
    """Ce qui se passerait, d'après l'état ACTUEL dans DN (pas celui de Grist, qui peut être en retard)."""
    _, label = await _label(dn, d, label_id)
    numeros = list(dict.fromkeys(numeros))
    trouves = {x.numero: x for x in await dn.dossiers(numeros, d.numero)}
    hors = [n for n in numeros if n in trouves and _hors(trouves[n], perimetre)]
    a_faire = [n for n in numeros if n in trouves and n not in hors and _besoin(trouves[n].labels, action, label_id)]
    introuvables = [n for n in numeros if n not in trouves]
    return {
        "action": action.value,
        "label": _vue_label(label),
        "total": len(numeros),
        "a_faire": len(a_faire),
        "deja": len(trouves) - len(a_faire) - len(hors),
        "introuvables": len(introuvables),
        "hors_perimetre": len(hors),
        "numeros_a_faire": a_faire,  # ≤ 500 (taille max d'une demande)
        "numeros_introuvables": introuvables[:50],
        "numeros_hors_perimetre": hors[:50],
    }


async def _maj_grist(grist: GristClient, d: DemarcheConfig, catalogue: list[Label],
                     etats: dict[int, frozenset[str]]) -> int:
    """Réécrit les colonnes de labels des dossiers dont l'état connu diffère de Grist."""
    if not etats:
        return 0
    cat = {l.id: l for l in catalogue}
    lignes = await lignes_grist(grist, d.table, [str(n) for n in etats])
    maj = []
    for n, labels in etats.items():
        ligne = lignes.get(str(n))
        attendus = frozenset(i for i in labels if i in cat)
        if ligne and ids_actuels(ligne.get("labels_json")) != attendus:
            maj.append({"id": ligne["id"], "fields": champs_otp([l.id for l in catalogue if l.id in attendus], cat)})
    if maj:
        await grist.maj(d.table, maj)
    return len(maj)


async def executer(
    dn: DNClient,
    grist: GristClient,
    d: DemarcheConfig,
    action: Action,
    label_id: str,
    numeros: Sequence[int],
    *,
    source: str,
    cle_schema: str,
    lignes_file: dict[int, list[int]] | None = None,
    perimetre: frozenset[int] | None = None,
    auteur: str = "",
) -> BilanOps:
    """Envoie à DN. `lignes_file` : {numéro: [ids LBL_Operations]} quand on traite la file d'attente.

    `perimetre` : groupes instructeurs autorisés (None = tous). Hors périmètre : refusé dans le journal ;
    en file d'attente, la ligne reste en attente (une personne habilitée pourra l'envoyer).
    """
    await assurer_schema(grist, cle_schema)
    await verifier_table_otp(grist, d.table)
    catalogue, label = await _label(dn, d, label_id)
    bilan = BilanOps(action.value, _vue_label(label))
    numeros = list(dict.fromkeys(numeros))

    trouves = {x.numero: x for x in await dn.dossiers(numeros, d.numero)}
    resultats: dict[int, tuple[str, str | None]] = {}
    etats: dict[int, frozenset[str]] = {}
    ops: list[tuple[int, Operation]] = []
    for n in numeros:
        dossier = trouves.get(n)
        if dossier is None:
            resultats[n] = ("erreur", "Dossier introuvable dans cette démarche")
            bilan.introuvables += 1
        elif _hors(dossier, perimetre):
            resultats[n] = ("refuse", MSG_HORS)
            bilan.hors_perimetre += 1
        elif not _besoin(dossier.labels, action, label_id):
            resultats[n] = ("deja_applique", None)
            etats[n] = dossier.labels
            bilan.deja += 1
        else:
            ops.append((n, Operation(dossier.id, label_id)))

    for (n, _op), r in zip(ops, await dn.appliquer(action, [op for _, op in ops]), strict=True):
        resultats[n] = (r.statut.value, r.message)
        if r.statut == Statut.ERREUR:
            bilan.erreurs += 1
            continue
        bilan.appliques += r.statut == Statut.APPLIQUE
        bilan.deja += r.statut == Statut.DEJA_APPLIQUE
        etats[n] = r.labels_apres if r.labels_apres is not None else _apres(trouves[n].labels, action, label_id)

    bilan.grist_maj = await _maj_grist(grist, d, catalogue, etats)

    now = time.time()
    if lignes_file is None:
        await grist.ajouter(JOURNAL, [
            {"demarche": d.numero, "dossier_number": str(n), "label_id": label_id, "label": label.nom,
             "action": action.value, "source": source, "statut": st, "message": msg or "",
             "cree_le": now, "traite_le": now, "auteur": auteur}
            for n, (st, msg) in resultats.items()
        ])
    else:
        maj = [{"id": rid, "fields": {"statut": st, "message": msg or "", "traite_le": now}}
               for n, (st, msg) in resultats.items() if st != "refuse" for rid in lignes_file.get(n, [])]
        if maj:
            await grist.maj(JOURNAL, maj)
    for n, (st, msg) in resultats.items():
        bilan.ajouter_detail(n, st, msg)
        bilan.statuts[n] = st
    return bilan


async def mettre_en_file(dn: DNClient, grist: GristClient, d: DemarcheConfig, action: Action, label_id: str,
                         numeros: Sequence[int], *, source: str, cle_schema: str, auteur: str = "") -> BilanOps:
    await assurer_schema(grist, cle_schema)
    _, label = await _label(dn, d, label_id)
    numeros = list(dict.fromkeys(numeros))
    now = time.time()
    await grist.ajouter(JOURNAL, [
        {"demarche": d.numero, "dossier_number": str(n), "label_id": label_id, "label": label.nom,
         "action": action.value, "source": source, "statut": "en_attente", "message": "", "cree_le": now,
         "auteur": auteur}
        for n in numeros
    ])
    return BilanOps(action.value, _vue_label(label), en_file=len(numeros))


async def envoyer_file(dn: DNClient, grist: GristClient, d: DemarcheConfig, *, cle_schema: str,
                       perimetre: frozenset[int] | None = None, auteur: str = "") -> list[BilanOps]:
    """Envoie les opérations en attente de la démarche, regroupées par (action, label).

    Hors du périmètre de l'expéditeur, les lignes restent en attente.
    """
    await assurer_schema(grist, cle_schema)
    rows = await grist.sql(
        f'SELECT id, dossier_number, label_id, action FROM "{JOURNAL}" '  # noqa: S608  # nosec B608 (constante)
        "WHERE demarche = ? AND statut = 'en_attente' ORDER BY id LIMIT ?",
        [d.numero, MAX_FILE],
    )
    groupes: dict[tuple[str, str], dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            action, numero = Action(r["action"]), int(str(r["dossier_number"]).strip())
        except ValueError:
            await grist.maj(JOURNAL, [{"id": r["id"], "fields": {"statut": "erreur", "message": "Ligne invalide"}}])
            continue
        groupes[(action.value, r["label_id"])][numero].append(r["id"])

    bilans = []
    for (action, label_id), lignes in groupes.items():
        try:
            bilans.append(await executer(dn, grist, d, Action(action), label_id, list(lignes), source="file",
                                         cle_schema=cle_schema, lignes_file=lignes, perimetre=perimetre,
                                         auteur=auteur))
        except LabelInconnu as exc:
            await grist.maj(JOURNAL, [{"id": i, "fields": {"statut": "erreur", "message": str(exc)}}
                                      for ids in lignes.values() for i in ids])
    return bilans


async def vider_journal(grist: GristClient, d: DemarcheConfig, *, cle_schema: str,
                        anterieures_a: float | None = None) -> int:
    """Supprime les entrées TRAITÉES du journal de la démarche ; les opérations en attente sont conservées.

    `anterieures_a` (horodatage) : ne supprime que les entrées traitées avant cette date (vidange automatique).
    """
    await assurer_schema(grist, cle_schema)
    sql = f'SELECT id FROM "{JOURNAL}" WHERE demarche = ? AND statut != ?'  # noqa: S608  # nosec B608 (constante)
    args: list[Any] = [d.numero, "en_attente"]
    if anterieures_a is not None:
        sql += " AND COALESCE(traite_le, cree_le) < ?"
        args.append(anterieures_a)
    rows = await grist.sql(sql, args)
    return await grist.supprimer(JOURNAL, [r["id"] for r in rows]) if rows else 0


async def vidange_automatique(grist: GristClient, d: DemarcheConfig, jours: int, *, cle_schema: str,
                              maintenant: float | None = None) -> int:
    """Applique la durée de conservation du journal ; ne fait rien si elle vaut 0."""
    if jours <= 0:
        return 0
    limite = (maintenant or time.time()) - jours * 86400
    return await vider_journal(grist, d, cle_schema=cle_schema, anterieures_a=limite)
