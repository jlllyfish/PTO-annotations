"""Synchronisation des labels DN → Grist.

Trois modes :
- incrementale : dossiers modifiés depuis la dernière synchro réussie (moins une marge) ;
  bascule en complète s'il n'y a jamais eu de synchro ;
- complete     : relecture de tous les dossiers (filet de sécurité, la nuit) ;
- ciblee       : une liste de numéros (bouton « synchroniser les dossiers affichés »).

Seules les lignes dont l'ENSEMBLE des labels a changé sont réécrites (pas de réécriture pour un
simple changement d'ordre), au format exact d'OTP pour que les deux outils restent cohérents.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from ..config import DemarcheConfig
from ..dn.client import DNClient, DossierLabels, Label
from ..grist.client import GristClient, ident
from .schema import assurer_schema, verifier_table_otp

MARGE = timedelta(minutes=2)
LOT_SQL = 500  # SQLite limite le nombre de paramètres par requête


class Mode(StrEnum):
    INCREMENTALE = "incrementale"
    COMPLETE = "complete"
    CIBLEE = "ciblee"


@dataclass
class Progression:
    etape: str = "en attente"
    dossiers_lus: int = 0

    def lus(self, n: int) -> None:
        self.dossiers_lus += n


@dataclass
class Bilan:
    demarche: int
    mode: Mode
    dossiers_lus: int = 0
    dossiers_maj: int = 0
    absents_grist: int = 0
    labels_catalogue: int = 0
    duree_s: float = 0.0
    numeros_maj: list[str] = field(default_factory=list)
    journal_purge: int = 0  # entrées de journal supprimées par la vidange automatique

    def resume(self) -> dict[str, Any]:
        d = asdict(self)
        d["numeros_maj"] = d["numeros_maj"][:50]
        return d


def champs_otp(ids: Sequence[str], catalogue: dict[str, Label]) -> dict[str, str]:
    """Reproduit `_build_label_fields` d'OTP (sync/tasks/labels.py)."""
    labels = [catalogue[i] for i in ids if i in catalogue]
    if not labels:
        return {"label_names": "", "labels_json": ""}
    return {
        "label_names": ", ".join(l.nom for l in labels),
        "labels_json": json.dumps(
            [{"id": l.id, "name": l.nom, "color": l.couleur} for l in labels], ensure_ascii=False
        ),
    }


def ids_actuels(labels_json: Any) -> frozenset[str] | None:
    """Ensemble des labels écrits dans Grist ; None si illisible (la ligne sera réécrite)."""
    if not labels_json:
        return frozenset()
    try:
        return frozenset(str(x["id"]) for x in json.loads(labels_json))
    except (ValueError, TypeError, KeyError):
        return None


def _epoch(dt: datetime) -> float:
    return round(dt.timestamp(), 3)


def _numero(v: Any) -> str:
    """OTP stocke dossier_number en texte ; on normalise quelle que soit la forme reçue."""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


async def lire_etat(grist: GristClient, demarche: int) -> dict[str, Any] | None:
    rows = await grist.sql('SELECT * FROM "LBL_Etat" WHERE demarche = ? LIMIT 1', [demarche])
    return rows[0] if rows else None


async def _maj_catalogue(grist: GristClient, demarche: int, labels: list[Label]) -> None:
    await grist.upsert(
        "LBL_Catalogue",
        [{"demarche": demarche, "label_id": l.id, "nom": l.nom, "couleur": l.couleur, "actif": True} for l in labels],
        ["demarche", "label_id"],
    )
    ids = {l.id for l in labels}
    anciens = await grist.sql('SELECT id, label_id FROM "LBL_Catalogue" WHERE demarche = ? AND actif', [demarche])
    if retires := [{"id": r["id"], "fields": {"actif": False}} for r in anciens if r["label_id"] not in ids]:
        await grist.maj("LBL_Catalogue", retires)


async def lignes_grist(grist: GristClient, table: str, numeros: Sequence[str] | None) -> dict[str, dict[str, Any]]:
    # Seul l'identifiant de table est inséré dans le texte : validé par ident() (regex + guillemets) et
    # issu de la configuration. Les valeurs passent toutes en paramètres « ? ».
    t = ident(table)
    if numeros is None:
        rows = await grist.sql(f"SELECT id, dossier_number, labels_json FROM {t}")  # noqa: S608  # nosec B608
    else:
        rows = []
        for i in range(0, len(numeros), LOT_SQL):
            lot = list(numeros[i : i + LOT_SQL])
            marques = ", ".join("?" * len(lot))
            rows += await grist.sql(
                f"SELECT id, dossier_number, labels_json FROM {t} WHERE dossier_number IN ({marques})",  # noqa: S608  # nosec B608
                lot,
            )
    return {_numero(r["dossier_number"]): r for r in rows}


async def synchroniser(
    dn: DNClient,
    grist: GristClient,
    demarche: DemarcheConfig,
    mode: Mode,
    *,
    cle_schema: str,
    numeros: Sequence[int] | None = None,
    progression: Progression | None = None,
    maintenant: datetime | None = None,
) -> Bilan:
    prog = progression or Progression()
    debut = maintenant or datetime.now(UTC)
    t0 = time.monotonic()
    n = demarche.numero

    prog.etape = "préparation"
    await assurer_schema(grist, cle_schema)
    await verifier_table_otp(grist, demarche.table)
    etat = await lire_etat(grist, n)

    try:
        prog.etape = "catalogue"
        labels = await dn.catalogue(n)
        await _maj_catalogue(grist, n, labels)
        catalogue = {l.id: l for l in labels}

        prog.etape = "lecture DN"
        dossiers: list[DossierLabels]
        if mode == Mode.CIBLEE:
            if not numeros:
                raise ValueError("aucun numéro de dossier")
            dossiers = await dn.dossiers(numeros, n, on_page=prog.lus)
        elif mode == Mode.INCREMENTALE and etat and etat.get("curseur"):
            depuis = datetime.fromtimestamp(float(etat["curseur"]), UTC) - MARGE
            dossiers = await dn.dossiers_modifies(n, depuis, on_page=prog.lus)
        else:
            mode = Mode.COMPLETE
            dossiers = await dn.tous_les_dossiers(n, on_page=prog.lus)

        prog.etape = "comparaison"
        bilan = Bilan(n, mode, dossiers_lus=len(dossiers), labels_catalogue=len(labels))
        cibles = None if mode == Mode.COMPLETE else [str(d.numero) for d in dossiers]
        lignes = await lignes_grist(grist, demarche.table, cibles) if dossiers else {}

        a_ecrire = []
        for d in dossiers:
            ligne = lignes.get(str(d.numero))
            if ligne is None:
                bilan.absents_grist += 1  # OTP ne l'a pas encore importé
                continue
            attendus = frozenset(i for i in d.labels if i in catalogue)
            if ids_actuels(ligne.get("labels_json")) == attendus:
                continue
            # Ordre stable : celui du catalogue DN
            ordonnes = [l.id for l in labels if l.id in attendus]
            a_ecrire.append({"id": ligne["id"], "fields": champs_otp(ordonnes, catalogue)})
            bilan.numeros_maj.append(str(d.numero))

        prog.etape = "écriture Grist"
        if a_ecrire:
            await grist.maj(demarche.table, a_ecrire)
        bilan.dossiers_maj = len(a_ecrire)
        bilan.duree_s = round(time.monotonic() - t0, 2)

        ligne_etat: dict[str, Any] = {
            "demarche": n, "mode": mode.value, "statut": "ok", "message": "",
            "debut": _epoch(debut), "fin": _epoch(datetime.now(UTC)), "duree_s": bilan.duree_s,
            "dossiers_lus": bilan.dossiers_lus, "dossiers_maj": bilan.dossiers_maj,
            "absents_grist": bilan.absents_grist,
        }
        if mode != Mode.CIBLEE:  # une synchro ciblée ne couvre pas tous les dossiers : le curseur ne bouge pas
            ligne_etat["curseur"] = _epoch(debut)
        if mode == Mode.COMPLETE:
            ligne_etat["derniere_complete"] = _epoch(debut)
        await grist.upsert("LBL_Etat", [ligne_etat], ["demarche"])
        prog.etape = "terminé"
        return bilan
    except Exception as exc:
        prog.etape = "erreur"
        with contextlib.suppress(Exception):  # ne pas masquer l'erreur d'origine
            await grist.upsert("LBL_Etat", [{
                "demarche": n, "mode": mode.value, "statut": "erreur", "message": str(exc)[:500],
                "debut": _epoch(debut), "fin": _epoch(datetime.now(UTC)),
            }], ["demarche"])
        raise
