"""Exécution des synchros en arrière-plan, une seule à la fois par (document, démarche).

Le widget lance une synchro puis interroge régulièrement son état (barre de progression).
L'état vit en mémoire : un redémarrage l'efface, mais le résultat durable est dans LBL_Etat.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .service import Bilan, Mode, Progression

log = logging.getLogger("sync")


class DejaEnCours(Exception):
    pass


@dataclass
class Tache:
    mode: Mode
    lancee_par: str
    progression: Progression = field(default_factory=Progression)
    debut: float = field(default_factory=time.time)
    fin: float | None = None
    statut: str = "en_cours"  # en_cours | ok | erreur
    bilan: Bilan | None = None
    erreur: str | None = None

    def vue(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "statut": self.statut,
            "etape": self.progression.etape,
            "dossiers_lus": self.progression.dossiers_lus,
            "debut": self.debut,
            "fin": self.fin,
            "lancee_par": self.lancee_par,
            "bilan": self.bilan.resume() if self.bilan else None,
            "erreur": self.erreur,
        }


class Taches:
    def __init__(self) -> None:
        self._taches: dict[tuple[str, int], Tache] = {}
        self._en_vol: set[asyncio.Task] = set()

    def etat(self, doc_id: str, demarche: int) -> Tache | None:
        return self._taches.get((doc_id, demarche))

    def _reserver(self, doc_id: str, demarche: int, mode: Mode, par: str) -> Tache:
        cle = (doc_id, demarche)
        actuelle = self._taches.get(cle)
        if actuelle and actuelle.statut == "en_cours":
            raise DejaEnCours(f"Synchro déjà en cours pour la démarche {demarche}")
        tache = Tache(mode=mode, lancee_par=par)
        self._taches[cle] = tache
        return tache

    async def _executer(self, tache: Tache, travail: Callable[[Progression], Awaitable[Bilan]]) -> Tache:
        try:
            tache.bilan = await travail(tache.progression)
            tache.statut = "ok"
        except Exception as exc:  # l'erreur est restituée au widget, pas propagée
            log.warning("Synchro en erreur : %s", exc)
            tache.statut, tache.erreur = "erreur", str(exc)[:500]
        finally:
            tache.fin = time.time()
        return tache

    def lancer(self, doc_id: str, demarche: int, mode: Mode, par: str,
               travail: Callable[[Progression], Awaitable[Bilan]]) -> Tache:
        """Lance en arrière-plan et rend la main tout de suite (widget)."""
        tache = self._reserver(doc_id, demarche, mode, par)
        t = asyncio.create_task(self._executer(tache, travail))
        self._en_vol.add(t)
        t.add_done_callback(self._en_vol.discard)
        return tache

    async def executer(self, doc_id: str, demarche: int, mode: Mode, par: str,
                       travail: Callable[[Progression], Awaitable[Bilan]]) -> Tache:
        """Exécute et attend la fin (tâches planifiées n8n)."""
        tache = self._reserver(doc_id, demarche, mode, par)
        return await self._executer(tache, travail)
