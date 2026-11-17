import json

import httpx
import pytest

from app.config import AppConfig

DOC = "AbCdEfGh1234"
BASE = f"https://grist.numerique.gouv.fr/o/mon-organisation/api/docs/{DOC}"
TOKEN = "tok_" + "a" * 40


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    # Isoler les tests des variables chargées depuis .env dans la session (hôtes autorisés, mode debug…)
    for var in ("LBL_ALLOWED_HOSTS", "LBL_DEBUG", "LBL_CONFIG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DN_TOKEN_TEST", "dn-secret")
    monkeypatch.setenv("GRIST_SERVICE_KEY", "grist-secret")


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate({
        "documents": [{
            "grist_doc_id": DOC,
            "nom": "Test",
            "demarches": [{"numero": 149930, "nom": "Western Pony Club", "dn_token": "DN_TOKEN_TEST"}],
        }]
    })


class Recorder:
    """Transport httpx factice qui enregistre les requêtes et délègue à un handler."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def _h(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return self.handler(request)
        return httpx.MockTransport(_h)

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.content]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class IdentificationFixe:
    """Remplace la sonde Grist dans les tests de routes."""

    def __init__(self, identite):
        self.identite = identite

    async def identifier(self, qui, client_utilisateur=None):
        return self.identite


class GroupesFixes:
    def __init__(self, groupes):
        self.liste = groupes

    async def groupes(self, dn, d):
        return self.liste


def installer_droits(app, *, email="camille@agriculture.gouv.fr", role="owners", groupes=(394762,)):
    from app.dn.client import GroupeInstructeur
    from app.identite import Identite
    app.state.identification = IdentificationFixe(Identite(email, 2949, "Camille", role) if email else None)
    app.state.groupes = GroupesFixes([GroupeInstructeur(g, f"Groupe {g}", False, frozenset({email or ""}))
                                      for g in groupes])
