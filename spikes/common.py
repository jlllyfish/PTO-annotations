"""Outils partagés par les scripts de test (phase 0).

Principes de sécurité appliqués partout :
- les secrets ne sont lus que depuis l'environnement (.env local) et ne sont jamais affichés ;
- les requêtes GraphQL passent leurs valeurs en `variables`, jamais par concaténation ;
- les requêtes SQL Grist passent leurs valeurs en `args` ; les noms de tables sont validés.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
load_dotenv(ROOT / ".env")

USER_AGENT = "labels-dn-grist-spikes/0.1"
TABLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
# En-têtes utiles pour comprendre les limites de débit ; on ne garde que ceux-là.
INTERESTING_HEADERS = ("ratelimit", "retry-after", "x-request-id", "x-runtime")


def env(name: str, *, required: bool = True, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        sys.exit(f"Variable d'environnement manquante : {name} (voir .env.example)")
    return value


def env_int(name: str, *, required: bool = True, default: int | None = None) -> int | None:
    raw = env(name, required=required, default=None if default is None else str(default))
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"{name} doit être un entier")


def env_list(name: str, *, required: bool = True) -> list[str]:
    raw = env(name, required=required) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def pick_headers(headers: httpx.Headers) -> dict[str, str]:
    return {k: v for k, v in headers.items() if any(h in k.lower() for h in INTERESTING_HEADERS)}


def save_result(name: str, payload: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{name}-{stamp}.json"
    payload = {"script": name, "date_utc": stamp, **payload}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ Résultats enregistrés : {path.relative_to(ROOT)}")
    return path


def require_flag(flag: str, explanation: str) -> None:
    if flag not in sys.argv:
        sys.exit(f"Ce script {explanation}.\nRelancez avec {flag} pour confirmer.")


# --------------------------------------------------------------------------- DN


@dataclass
class GqlResult:
    status: int
    ms: float
    data: dict[str, Any] | None
    errors: list[dict[str, Any]] | None
    headers: dict[str, str]
    bytes: int

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.errors and self.data is not None


class DN:
    def __init__(self) -> None:
        self.url = env("DN_API_URL", default="https://demarche.numerique.gouv.fr/api/v2/graphql")
        token = env("DN_TOKEN")
        self.client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

    async def gql(self, query: str, variables: dict[str, Any] | None = None) -> GqlResult:
        start = time.perf_counter()
        resp = await self.client.post(self.url, json={"query": query, "variables": variables or {}})
        ms = (time.perf_counter() - start) * 1000
        try:
            body = resp.json()
        except ValueError:
            body = {"errors": [{"message": f"Réponse non JSON (HTTP {resp.status_code})"}]}
        return GqlResult(
            status=resp.status_code,
            ms=round(ms, 1),
            data=body.get("data"),
            errors=body.get("errors"),
            headers=pick_headers(resp.headers),
            bytes=len(resp.content),
        )

    async def close(self) -> None:
        await self.client.aclose()


# ------------------------------------------------------------------------ Grist


class Grist:
    def __init__(self) -> None:
        base = env("GRIST_BASE_URL", default="https://grist.numerique.gouv.fr/api").rstrip("/")
        doc = env("GRIST_DOC_ID")
        if not re.fullmatch(r"[A-Za-z0-9]{10,64}", doc or ""):
            sys.exit("GRIST_DOC_ID a un format inattendu")
        self.doc_url = f"{base}/docs/{doc}"
        self.client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"Authorization": f"Bearer {env('GRIST_API_KEY')}", "User-Agent": USER_AGENT},
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> tuple[int, float, Any]:
        start = time.perf_counter()
        resp = await self.client.request(method, f"{self.doc_url}{path}", **kwargs)
        ms = round((time.perf_counter() - start) * 1000, 1)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:500]
        return resp.status_code, ms, body

    async def sql(self, sql: str, args: list[Any] | None = None) -> tuple[int, float, Any]:
        return await self.request("POST", "/sql", json={"sql": sql, "args": args or []})

    async def table_ids(self) -> list[str]:
        status, _, body = await self.request("GET", "/tables")
        if status != 200:
            sys.exit(f"Lecture des tables Grist impossible (HTTP {status}) : {body}")
        return [t["id"] for t in body.get("tables", [])]

    async def close(self) -> None:
        await self.client.aclose()


def safe_table(table_id: str, existing: list[str]) -> str:
    """Valide un identifiant de table avant de l'insérer dans du SQL (non paramétrable)."""
    if not TABLE_ID_RE.fullmatch(table_id) or table_id not in existing:
        sys.exit(f"Table invalide ou absente du document : {table_id!r}")
    return f'"{table_id}"'
