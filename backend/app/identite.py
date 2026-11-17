"""Identité de l'utilisateur du widget, certifiée par Grist (et non déclarée par le navigateur).

Procédé (validé par le script spikes/verif_identite.py) :
1. avec le JETON de l'utilisateur, le backend crée une ligne « sonde » dans LBL_Sessions ;
   Grist remplit lui-même email / user_id / acces / nom par des formules déclenchées ;
2. avec la CLÉ DE SERVICE, le backend relit cette ligne, la supprime, puis vérifie :
   - que les formules de LBL_Sessions n'ont pas été modifiées (un éditeur pourrait les remplacer par une constante) ;
   - que l'identifiant et l'adresse concordent avec la liste des membres du document (fournie par Grist,
     hors de toute formule) ; le rôle retenu est celui de cette liste.
Un utilisateur en lecture seule ne peut pas écrire la sonde : il reste anonyme, donc sans droit d'action.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

from .config import AppConfig, read_secret
from .grist.client import GristClient, GristError
from .security import Appelant
from .sync.schema import assurer_schema, reparer_triggers, triggers_conformes

log = logging.getLogger("identite")
SESSIONS = "LBL_Sessions"
ROLES = {"owners": 3, "editors": 2, "viewers": 1}


class IdentiteDouteuse(Exception):
    """Les éléments d'identité ne concordent pas : on refuse plutôt que de deviner."""


@dataclass(frozen=True)
class Identite:
    email: str
    user_id: int
    nom: str
    role: str | None   # owners / editors / viewers

    @property
    def proprietaire(self) -> bool:
        return self.role == "owners"

    @property
    def editeur(self) -> bool:
        return ROLES.get(self.role or "", 0) >= ROLES["editors"]


def role_effectif(membre: dict[str, Any]) -> str | None:
    roles = [r for r in (membre.get("access"), membre.get("parentAccess")) if r in ROLES]
    return max(roles, key=ROLES.__getitem__) if roles else None


class Identification:
    def __init__(self, config: AppConfig, *, ttl: float = 120.0, ttl_membres: float = 300.0,
                 transport: httpx.AsyncBaseTransport | None = None, fabrique_service=None) -> None:
        self._config = config
        self._ttl = ttl
        self._ttl_membres = ttl_membres
        self._transport = transport
        self._cache: OrderedDict[str, tuple[float, Identite | None]] = OrderedDict()
        self._membres: dict[str, tuple[float, dict[int, dict[str, Any]]]] = {}
        # Permet aux tests de fournir un faux client « clé de service »
        self._fabrique_service = fabrique_service or self._client_service

    def _client_service(self, doc_id: str) -> GristClient:
        return GristClient.par_cle(self._config.grist_host, doc_id, read_secret(self._config.grist_service_key),
                                   transport=self._transport)

    async def identifier(self, qui: Appelant, client_utilisateur: Any = None) -> Identite | None:
        """Identité certifiée, ou None si l'utilisateur ne peut pas écrire (lecture seule)."""
        doc_id = qui.document.grist_doc_id
        cle = hashlib.sha256(f"{doc_id}:{qui.token}".encode()).hexdigest()
        now = time.monotonic()
        if (hit := self._cache.get(cle)) and hit[0] > now:
            return hit[1]

        identite = await self._sonder(qui, doc_id, client_utilisateur)
        self._cache[cle] = (now + self._ttl, identite)
        while len(self._cache) > 2000:
            self._cache.popitem(last=False)
        return identite

    async def _sonder(self, qui: Appelant, doc_id: str, client_utilisateur: Any) -> Identite | None:
        jeton = secrets.token_hex(16)
        async with self._fabrique_service(doc_id) as service:
            await assurer_schema(service, doc_id)
            utilisateur = client_utilisateur or qui.grist(self._transport)
            try:
                async with utilisateur as g:
                    await g.ajouter(SESSIONS, [{"jeton": jeton, "cree_le": time.time()}])
            except GristError as exc:
                if exc.status in (401, 403):
                    return None  # lecture seule
                raise
            # Sonde + sondes oubliées (> 1 h), formules et membres : lus en parallèle
            lus, colonnes, membres = await asyncio.gather(
                service.sql(f'SELECT * FROM "{SESSIONS}" WHERE jeton = ? OR cree_le < ?',  # noqa: S608  # nosec B608
                            [jeton, time.time() - 3600]),
                service.colonnes(SESSIONS),
                self._liste_membres(service, doc_id),
            )
            if ids := sorted(r["id"] for r in lus):
                await service.supprimer(SESSIONS, ids)
            rows = [r for r in lus if r.get("jeton") == jeton]
            if len(rows) != 1:
                raise IdentiteDouteuse("sonde d'identité introuvable")
            if not triggers_conformes(colonnes):
                await reparer_triggers(service)
                log.warning("Formules de LBL_Sessions modifiées dans le document %s : réparées, identification refusée",
                            doc_id)
                raise IdentiteDouteuse("formules d'identification modifiées dans le document")
            sonde = rows[0]
            try:
                user_id = int(sonde.get("user_id"))
            except (TypeError, ValueError):
                raise IdentiteDouteuse("identifiant Grist absent") from None
            email = str(sonde.get("email") or "").strip().lower()
            membre = membres.get(user_id)
            if not membre or str(membre.get("email") or "").strip().lower() != email or not email:
                raise IdentiteDouteuse("identité incohérente avec les membres du document")
            return Identite(email=email, user_id=user_id, nom=str(sonde.get("nom") or ""), role=role_effectif(membre))

    async def _liste_membres(self, service: GristClient, doc_id: str) -> dict[int, dict[str, Any]]:
        now = time.monotonic()
        if (hit := self._membres.get(doc_id)) and hit[0] > now:
            return hit[1]
        membres = {int(m["id"]): m for m in await service.membres() if m.get("id") is not None}
        self._membres[doc_id] = (now + self._ttl_membres, membres)
        return membres
