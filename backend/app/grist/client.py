"""Client de l'API REST Grist pour UN document.

Deux modes d'authentification :
- `GristClient.par_cle(...)`   : clé API du compte de service (tâches de fond) ;
- `GristClient.par_jeton(...)` : jeton d'accès émis par le widget (actions d'un utilisateur ;
  l'historique Grist est nominatif et les règles d'accès du document s'appliquent).

Constats de la phase 0 : `/sql` n'accepte que SELECT, paramètres liés via `args` ;
upsert natif `PUT /records` + `require` ; `dossier_number` est stocké en texte par OTP.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

TABLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
COL_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
LOT_ECRITURE = 500


class GristError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def ident(name: str, *, kind: str = "table") -> str:
    """Valide puis cite un identifiant (table ou colonne) pour l'insérer dans du SQL.

    Les identifiants ne sont pas paramétrables en SQL : ils doivent en plus avoir été
    vérifiés contre le schéma réel du document par l'appelant.
    """
    regex = TABLE_ID_RE if kind == "table" else COL_ID_RE
    if not regex.fullmatch(name):
        raise ValueError(f"identifiant {kind} invalide : {name!r}")
    return f'"{name}"'


@dataclass(frozen=True)
class Colonne:
    id: str
    type: str  # Text, Numeric, Int, Bool, Date, DateTime:<tz>, Choice, ChoiceList, Ref:<T>…
    libelle: str
    choix: tuple[str, ...] = ()  # valeurs déclarées d'une colonne Choice / ChoiceList
    # Métadonnées de formule (formula, isFormula, recalcWhen, recalcDeps, colRef) : contrôle des formules déclenchées
    meta: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

META_FORMULE = ("formula", "isFormula", "recalcWhen", "recalcDeps", "colRef")


def _choix(fields: dict[str, Any]) -> tuple[str, ...]:
    try:
        opts = json.loads(fields.get("widgetOptions") or "{}")
    except (ValueError, TypeError):
        return ()
    return tuple(str(c) for c in (opts.get("choices") or [])[:500] if isinstance(c, str | int | float))


class GristClient:
    def __init__(self, doc_url: str, *, headers: dict[str, str], params: dict[str, str],
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=doc_url.rstrip("/"),
            headers={"User-Agent": "labels-dn-grist/1.0", **headers},
            params=params,
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
            follow_redirects=False,
        )

    @classmethod
    def par_cle(cls, host: str, doc_id: str, api_key: str, **kw: Any) -> GristClient:
        return cls(f"https://{host}/api/docs/{doc_id}", headers={"Authorization": f"Bearer {api_key}"}, params={}, **kw)

    @classmethod
    def par_jeton(cls, base_url: str, token: str, **kw: Any) -> GristClient:
        """`base_url` doit avoir été validée (voir security.verifier_base_url)."""
        return cls(base_url, headers={}, params={"auth": token}, **kw)

    # Client « clé de service » pour les lectures SQL : l'endpoint /sql de Grist exige de pouvoir lire
    # tout le document, ce que les règles d'accès refusent aux non-propriétaires. Les écritures, elles,
    # restent faites avec le jeton de l'utilisateur (ses droits Grist s'appliquent).
    lecteur: GristClient | None = None

    async def aclose(self) -> None:
        await self._http.aclose()
        if self.lecteur is not None:
            await self.lecteur.aclose()

    async def __aenter__(self) -> GristClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        try:
            resp = await self._http.request(method, path, **kw)
        except httpx.TransportError as exc:
            raise GristError(f"Grist injoignable ({exc.__class__.__name__})") from None
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", "")
            except ValueError:
                detail = ""
            raise GristError(f"Grist HTTP {resp.status_code} {detail}".strip()[:300], status=resp.status_code)
        return resp.json() if resp.content else None

    # ------------------------------------------------------------------ lecture

    async def tables(self) -> list[str]:
        body = await self._req("GET", "/tables")
        return [t["id"] for t in body.get("tables", [])]

    async def colonnes(self, table: str) -> list[Colonne]:
        ident(table)
        body = await self._req("GET", f"/tables/{table}/columns")
        return [
            Colonne(c["id"], c["fields"].get("type", "Any"), c["fields"].get("label") or c["id"], _choix(c["fields"]),
                    {k: c["fields"].get(k) for k in META_FORMULE})
            for c in body.get("columns", [])
            if not c["id"].startswith("gristHelper_")
        ]

    async def sql(self, sql: str, args: Sequence[Any] = ()) -> list[dict[str, Any]]:
        if self.lecteur is not None:
            return await self.lecteur.sql(sql, args)
        body = await self._req("POST", "/sql", json={"sql": sql, "args": list(args), "timeout": 5000})
        return [r["fields"] for r in body.get("records", [])]

    # ------------------------------------------------------------------ schéma

    @staticmethod
    def _defs(colonnes: Sequence[tuple[str, str | dict[str, Any]]]) -> list[dict[str, Any]]:
        """(id, type) ou (id, {champs de colonne}) → définitions de colonnes de l'API."""
        return [{"id": ident(c, kind="colonne") and c, "fields": t if isinstance(t, dict) else {"type": t}}
                for c, t in colonnes]

    async def creer_table(self, table: str, colonnes: Sequence[tuple[str, str | dict[str, Any]]]) -> None:
        ident(table)
        await self._req("POST", "/tables", json={"tables": [{"id": table, "columns": self._defs(colonnes)}]})

    async def ajouter_colonnes(self, table: str, colonnes: Sequence[tuple[str, str | dict[str, Any]]]) -> None:
        ident(table)
        await self._req("POST", f"/tables/{table}/columns", json={"columns": self._defs(colonnes)})

    async def maj_colonnes(self, table: str, colonnes: Sequence[dict[str, Any]]) -> None:
        ident(table)
        await self._req("PATCH", f"/tables/{table}/columns", json={"columns": list(colonnes)})

    async def membres(self) -> list[dict[str, Any]]:
        """Membres du document (exige les droits de propriétaire) : id, email, access, parentAccess."""
        body = await self._req("GET", "/access")
        return list(body.get("users", []))

    # ------------------------------------------------------------------ écriture

    async def upsert(self, table: str, lignes: Sequence[dict[str, Any]], cles: Sequence[str]) -> int:
        """Ajoute ou met à jour selon `cles` (upsert natif Grist), par lots de 500."""
        ident(table)
        for c in cles:
            ident(c, kind="colonne")
        n = 0
        for i in range(0, len(lignes), LOT_ECRITURE):
            lot = lignes[i : i + LOT_ECRITURE]
            records = [
                {"require": {c: l[c] for c in cles}, "fields": {k: v for k, v in l.items() if k not in cles}}
                for l in lot
            ]
            await self._req("PUT", f"/tables/{table}/records", json={"records": records})
            n += len(lot)
        return n

    async def ajouter(self, table: str, lignes: Sequence[dict[str, Any]]) -> int:
        ident(table)
        for i in range(0, len(lignes), LOT_ECRITURE):
            lot = [{"fields": l} for l in lignes[i : i + LOT_ECRITURE]]
            await self._req("POST", f"/tables/{table}/records", json={"records": lot})
        return len(lignes)

    async def supprimer(self, table: str, ids: Sequence[int]) -> int:
        ident(table)
        ids = [int(i) for i in ids]
        for i in range(0, len(ids), LOT_ECRITURE):
            await self._req("POST", "/apply", json=[["BulkRemoveRecord", table, ids[i : i + LOT_ECRITURE]]])
        return len(ids)

    async def maj(self, table: str, lignes: Sequence[dict[str, Any]]) -> int:
        """Mise à jour par identifiant de ligne Grist : [{"id": 12, "fields": {...}}, …]."""
        ident(table)
        for i in range(0, len(lignes), LOT_ECRITURE):
            await self._req("PATCH", f"/tables/{table}/records", json={"records": list(lignes[i : i + LOT_ECRITURE])})
        return len(lignes)
