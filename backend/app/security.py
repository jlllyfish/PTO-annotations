"""Authentification du widget par jeton d'accès Grist.

Le widget obtient un jeton via `grist.docApi.getAccessToken()` et l'envoie avec la `baseUrl`
du document. Le backend :
1. valide la `baseUrl` (hôte Grist attendu, chemin `/o/<org>/api/docs/<docId>`) ;
2. vérifie que ce document est déclaré dans `demarches.yaml` — AVANT tout appel réseau ;
3. prouve le jeton en appelant Grist avec lui (HTTP 200 = l'appelant a accès au document) ;
4. garde ce résultat en cache peu de temps (clé = empreinte du jeton, jamais le jeton).
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import AppConfig, DocumentConfig
from .grist.client import GristClient, GristError

DOC_PATH_RE = re.compile(r"^(?:/o/[A-Za-z0-9-]{1,64})?/api/docs/([A-Za-z0-9]{10,64})$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{10,1024}$")


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


def verifier_base_url(base_url: str, host_attendu: str) -> str:
    """Renvoie l'identifiant du document si la baseUrl est acceptable, sinon AuthError."""
    parts = urlsplit(base_url)
    if (
        parts.scheme != "https"
        or parts.hostname != host_attendu
        or parts.port is not None
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise AuthError("baseUrl refusée", 400)
    m = DOC_PATH_RE.fullmatch(parts.path)
    if not m:
        raise AuthError("baseUrl refusée", 400)
    return m.group(1)


@dataclass(frozen=True)
class Appelant:
    document: DocumentConfig
    base_url: str
    token: str

    def grist(self, transport: httpx.AsyncBaseTransport | None = None) -> GristClient:
        return GristClient.par_jeton(self.base_url, self.token, transport=transport)


class VerificateurJetons:
    def __init__(self, config: AppConfig, *, ttl: float = 120.0, taille: int = 2000,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._config = config
        self._ttl = ttl
        self._taille = taille
        self._transport = transport
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()

    async def verifier(self, token: str | None, base_url: str | None) -> Appelant:
        if not token or not base_url:
            raise AuthError("Jeton Grist absent")
        if not TOKEN_RE.fullmatch(token):
            raise AuthError("Jeton Grist mal formé")
        doc_id = verifier_base_url(base_url, self._config.grist_host)
        document = self._config.document(doc_id)
        if document is None:
            raise AuthError("Document Grist non configuré pour cet outil", 403)

        cle = hashlib.sha256(f"{doc_id}:{token}".encode()).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(cle)
        if hit and hit[0] > now and hit[1] == doc_id:
            self._cache.move_to_end(cle)
            return Appelant(document, base_url, token)

        try:
            async with GristClient.par_jeton(base_url, token, transport=self._transport) as g:
                await g.tables()
        except GristError as exc:
            if exc.status in (401, 403, 404):
                raise AuthError("Jeton Grist refusé par Grist", 401) from None
            raise AuthError("Vérification Grist impossible", 503) from None

        self._cache[cle] = (now + self._ttl, doc_id)
        while len(self._cache) > self._taille:
            self._cache.popitem(last=False)
        return Appelant(document, base_url, token)


class LimiteurDebit:
    """Fenêtre glissante simple, par document : protège DN et Grist d'un widget emballé."""

    def __init__(self, par_minute: int = 120) -> None:
        self._max = par_minute
        self._appels: dict[str, list[float]] = {}

    def verifier(self, cle: str) -> None:
        now = time.monotonic()
        fenetre = [t for t in self._appels.get(cle, []) if now - t < 60]
        if len(fenetre) >= self._max:
            raise AuthError("Trop de requêtes, réessayez dans une minute", 429)
        fenetre.append(now)
        self._appels[cle] = fenetre
