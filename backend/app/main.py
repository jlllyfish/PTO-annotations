"""Application FastAPI : sert le widget et l'API, avec des en-têtes de sécurité stricts."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.ops_routes import router as ops_router
from .api.regles_routes import router as regles_router
from .api.routes import router
from .api.sync_routes import router as sync_router
from .config import AppConfig, get_config, read_secret
from .dn.client import DNClient, DNError
from .droits import CacheGroupes
from .grist.client import GristError
from .identite import Identification
from .regles.service import cle_regles
from .security import LimiteurDebit, VerificateurJetons
from .sync.jobs import Taches

STATIC = Path(__file__).parent / "static"
MAX_BODY = 256 * 1024

logging.basicConfig(level=os.getenv("LBL_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
# httpx journalise les URL en INFO : elles peuvent contenir le jeton Grist (?auth=). On les coupe.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class JSONUtf8(JSONResponse):
    """Précise le charset : PowerShell 5 lit sinon les accents en ISO-8859-1."""

    media_type = "application/json; charset=utf-8"


class FabriqueDN:
    """Un client DN (et son pool de connexions) par jeton configuré, créé à la demande."""

    def __init__(self, config: AppConfig, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._config = config
        self._transport = transport
        self._clients: dict[str, DNClient] = {}

    def __call__(self, secret_name: str) -> DNClient:
        if secret_name not in self._clients:
            self._clients[secret_name] = DNClient(
                str(self._config.dn_api_url), read_secret(secret_name),
                concurrence=self._config.dn_concurrence, transport=self._transport,
            )
        return self._clients[secret_name]

    async def aclose(self) -> None:
        for c in self._clients.values():
            await c.aclose()


def create_app(
    config: AppConfig | None = None,
    *,
    dn_transport: httpx.AsyncBaseTransport | None = None,
    grist_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    config = config or get_config()
    fabrique = FabriqueDN(config, dn_transport)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        await fabrique.aclose()

    debug = os.getenv("LBL_DEBUG") == "1"
    app = FastAPI(
        title="Labels DN ↔ Grist",
        lifespan=lifespan,
        default_response_class=JSONUtf8,
        docs_url="/docs" if debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if debug else None,
    )
    app.state.config = config
    app.state.verificateur = VerificateurJetons(config, transport=grist_transport)
    app.state.limiteur = LimiteurDebit()
    app.state.dn_clients = fabrique
    app.state.grist_transport = grist_transport
    app.state.taches = Taches()
    app.state.identification = Identification(config, transport=grist_transport)
    app.state.groupes = CacheGroupes()
    app.state.cle_regles = cle_regles(read_secret(config.grist_service_key))

    if hosts := os.getenv("LBL_ALLOWED_HOSTS"):
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in hosts.split(",")])

    grist = f"https://{config.grist_host}"
    csp_widget = (
        "default-src 'none'; "
        # 'unsafe-eval' : exigé par grist-plugin-api.js (constat phase 0). Aucun script inline.
        f"script-src 'self' 'unsafe-eval' {grist}; "
        "style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; "
        f"frame-ancestors {grist}; base-uri 'none'; form-action 'none'"
    )
    csp_api = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

    @app.middleware("http")
    async def securite(request: Request, call_next):
        longueur = request.headers.get("content-length")
        if longueur and (not longueur.isdigit() or int(longueur) > MAX_BODY):
            return JSONUtf8({"detail": "Requête trop volumineuse"}, status_code=413)
        response = await call_next(request)
        widget = request.url.path.startswith("/widget")
        h = response.headers
        h["Content-Security-Policy"] = csp_widget if widget else csp_api
        h["X-Content-Type-Options"] = "nosniff"
        h["Referrer-Policy"] = "no-referrer"
        h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        # Widget : revalidation à chaque chargement (sinon une mise à jour peut rester invisible dans Grist)
        h["Cache-Control"] = "no-cache" if widget else "no-store"
        return response

    @app.exception_handler(DNError)
    async def _dn(_req: Request, exc: DNError) -> JSONResponse:
        logging.getLogger("dn").warning("Erreur DN : %s (request-id %s)", exc, exc.request_id)
        return JSONUtf8({"detail": str(exc), "source": "dn", "request_id": exc.request_id}, status_code=502)

    @app.exception_handler(GristError)
    async def _grist(_req: Request, exc: GristError) -> JSONResponse:
        logging.getLogger("grist").warning("Erreur Grist : %s", exc)
        return JSONUtf8({"detail": str(exc), "source": "grist"}, status_code=502)

    app.include_router(router)
    app.include_router(sync_router)
    app.include_router(ops_router)
    app.include_router(regles_router)
    app.mount("/widget", StaticFiles(directory=STATIC, html=True), name="widget")
    return app
