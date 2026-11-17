"""Droits d'un utilisateur du widget sur une démarche.

- Identité : certifiée par Grist (voir identite.py). Sans identité (lecture seule) : aucune action.
- Groupes : l'adresse certifiée est cherchée parmi les instructeurs des groupes de la démarche, lus dans DN
  (source de vérité ; la table d'instructeurs d'OTP ne sert qu'à l'affichage).
- Règles automatiques et vidage du journal : propriétaires du document Grist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import DemarcheConfig
from .dn.client import DNClient, GroupeInstructeur
from .identite import Identite

MSG_HORS = "Hors de vos groupes instructeurs"


@dataclass(frozen=True)
class Droits:
    identite: Identite | None
    controle: bool
    groupes: tuple[GroupeInstructeur, ...] = field(default=())

    @property
    def perimetre(self) -> frozenset[int] | None:
        """Numéros de groupes autorisés ; None = pas de restriction (contrôle désactivé)."""
        return frozenset(g.numero for g in self.groupes) if self.controle else None

    @property
    def peut_agir(self) -> bool:
        return bool(self.identite and self.identite.editeur and (not self.controle or self.groupes))

    @property
    def proprietaire(self) -> bool:
        return bool(self.identite and self.identite.proprietaire)

    def raison_refus(self) -> str | None:
        if self.identite is None:
            return "Accès en lecture seule au document : aucune action possible"
        if not self.identite.editeur:
            return "Accès en lecture seule au document : aucune action possible"
        if self.controle and not self.groupes:
            return "Votre adresse n'est instructrice d'aucun groupe de cette démarche dans Démarche Numérique"
        return None

    def vue(self) -> dict:
        i = self.identite
        return {
            "utilisateur": {"email": i.email, "nom": i.nom, "role": i.role} if i else None,
            "controle_instructeurs": self.controle,
            "groupes": [{"numero": g.numero, "libelle": g.libelle} for g in self.groupes],
            "peut_agir": self.peut_agir,
            "proprietaire": self.proprietaire,
            "raison": self.raison_refus(),
        }


class CacheGroupes:
    """Groupes instructeurs par démarche (et par jeton DN), relus au plus toutes les `ttl` secondes."""

    def __init__(self, ttl: float = 600.0) -> None:
        self._ttl = ttl
        self._cache: dict[tuple[str, int], tuple[float, list[GroupeInstructeur]]] = {}

    async def groupes(self, dn: DNClient, d: DemarcheConfig) -> list[GroupeInstructeur]:
        cle = (d.dn_token, d.numero)
        now = time.monotonic()
        if (hit := self._cache.get(cle)) and hit[0] > now:
            return hit[1]
        groupes = await dn.groupes(d.numero)
        self._cache[cle] = (now + self._ttl, groupes)
        return groupes


async def calculer(identite: Identite | None, dn: DNClient, d: DemarcheConfig, cache: CacheGroupes) -> Droits:
    if not d.controle_instructeurs:
        return Droits(identite, controle=False)
    if identite is None:
        return Droits(None, controle=True)
    mes = tuple(g for g in await cache.groupes(dn, d) if identite.email in g.emails)
    return Droits(identite, controle=True, groupes=mes)
