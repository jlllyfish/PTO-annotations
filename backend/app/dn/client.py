"""Client de l'API GraphQL de Démarche Numérique, limité à ce dont l'outil a besoin.

Constats de la phase 0 appliqués ici :
- `first` est plafonné en silence à 100 → pages de 100, on suit toujours `hasNextPage` ;
- un changement de label met à jour `dateDerniereModification` → lecture incrémentale `updatedSince` ;
- lecture ciblée `dossier(number:)` par alias : ≈ 30 ms/dossier → lots de 25 en parallèle ;
- mutations par alias : lots de 50 ; erreurs rattachées à l'alias via `path` ;
- pas d'idempotence native : « déjà associé » / « pas associé » = état déjà atteint ;
- pas d'en-tête de limite : concurrence bornée + nouvelle tentative sur 429/5xx.

Toutes les valeurs passent par `variables` ; le texte des requêtes ne dépend que de constantes
et d'entiers validés.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

import httpx

log = logging.getLogger("dn")

PAGE = 100
LOT_LECTURE = 25
LOT_MUTATION = 50
ETATS = ("en_construction", "en_instruction", "accepte", "refuse", "sans_suite")
RETRY_STATUSES = {429, 502, 503, 504}


class DNError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


@dataclass(frozen=True)
class Label:
    id: str
    nom: str
    couleur: str


@dataclass(frozen=True)
class DossierLabels:
    numero: int
    id: str
    labels: frozenset[str]
    modifie_le: str | None = None


class Action(StrEnum):
    AJOUTER = "ajouter"
    RETIRER = "retirer"


class Statut(StrEnum):
    APPLIQUE = "applique"
    DEJA_APPLIQUE = "deja_applique"
    ERREUR = "erreur"


@dataclass(frozen=True)
class Operation:
    dossier_id: str
    label_id: str


@dataclass(frozen=True)
class Resultat:
    operation: Operation
    statut: Statut
    message: str | None = None
    labels_apres: frozenset[str] | None = None


_MUTATIONS = {
    Action.AJOUTER: ("dossierAjouterLabel", "DossierAjouterLabelInput"),
    Action.RETIRER: ("dossierSupprimerLabel", "DossierSupprimerLabelInput"),
}
# Messages DN signifiant « l'état voulu est déjà atteint » (constatés en phase 0).
_DEJA = {
    Action.AJOUTER: ("déjà associé",),
    Action.RETIRER: ("pas associé",),
}

Q_CATALOGUE = """
query Catalogue($n: Int!) { demarche(number: $n) { labels { id name color } } }
"""
_DOSSIER_FIELDS = "id number dateDerniereModification labels { id }"
Q_DOSSIERS = f"""
query Dossiers($n: Int!, $after: String, $since: ISO8601DateTime) {{
  demarche(number: $n) {{
    dossiers(first: {PAGE}, after: $after, updatedSince: $since) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_DOSSIER_FIELDS} }}
    }}
  }}
}}
"""
Q_DOSSIERS_ETAT = f"""
query DossiersEtat($n: Int!, $after: String, $state: DossierState!) {{
  demarche(number: $n) {{
    dossiers(first: {PAGE}, after: $after, state: $state) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ {_DOSSIER_FIELDS} }}
    }}
  }}
}}
"""


def _query_lecture_ciblee(n: int) -> str:
    if not 1 <= n <= LOT_LECTURE:
        raise ValueError("taille de lot invalide")
    decl = ", ".join(f"$n{k}: Int!" for k in range(n))
    body = " ".join(f"d{k}: dossier(number: $n{k}) {{ {_DOSSIER_FIELDS} }}" for k in range(n))
    return f"query Cible({decl}) {{ {body} }}"


def _query_mutation(action: Action, n: int) -> str:
    if not 1 <= n <= LOT_MUTATION:
        raise ValueError("taille de lot invalide")
    field, input_type = _MUTATIONS[action]
    decl = ", ".join(f"$i{k}: {input_type}!" for k in range(n))
    body = " ".join(
        f"m{k}: {field}(input: $i{k}) {{ dossier {{ labels {{ id }} }} errors {{ message }} }}" for k in range(n)
    )
    return f"mutation Lot({decl}) {{ {body} }}"


def _dossier(node: dict[str, Any]) -> DossierLabels:
    return DossierLabels(
        numero=int(node["number"]),
        id=str(node["id"]),
        labels=frozenset(lbl["id"] for lbl in node.get("labels") or []),
        modifie_le=node.get("dateDerniereModification"),
    )


def _chunks(seq: Sequence[Any], size: int) -> list[Sequence[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


class DNClient:
    def __init__(
        self,
        url: str,
        token: str,
        *,
        concurrence: int = 4,
        tentatives: int = 4,
        delai_base: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sem = asyncio.Semaphore(concurrence)
        self._tentatives = tentatives
        self._delai_base = delai_base
        self._http = httpx.AsyncClient(
            base_url=url,
            transport=transport,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "labels-dn-grist/1.0"},
            follow_redirects=False,
        )
        self._url = url

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> DNClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ transport

    async def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Renvoie le corps JSON complet ({data, errors}). Lève DNError sur erreur HTTP."""
        for essai in range(1, self._tentatives + 1):
            async with self._sem:
                try:
                    resp = await self._http.post("", json={"query": query, "variables": variables})
                except httpx.TransportError as exc:
                    if essai == self._tentatives:
                        raise DNError(f"DN injoignable ({exc.__class__.__name__})") from None
                    await self._attendre(essai, None)
                    continue
            rid = resp.headers.get("x-request-id")
            if resp.status_code in RETRY_STATUSES and essai < self._tentatives:
                log.warning("DN HTTP %s, nouvelle tentative %s (request-id %s)", resp.status_code, essai, rid)
                await self._attendre(essai, resp.headers.get("retry-after"))
                continue
            if resp.status_code != 200:
                raise DNError(_message_http(resp), status=resp.status_code, request_id=rid)
            try:
                return resp.json()
            except ValueError:
                raise DNError("Réponse DN non JSON", status=200, request_id=rid) from None
        raise DNError("Échec après nouvelles tentatives")  # pragma: no cover

    async def _attendre(self, essai: int, retry_after: str | None) -> None:
        try:
            delai = min(float(retry_after), 60.0) if retry_after else None
        except ValueError:
            delai = None
        if delai is None:  # gigue aléatoire : usage non cryptographique
            delai = self._delai_base * 2 ** (essai - 1) * (1 + random.random() / 2)  # noqa: S311  # nosec B311
        await asyncio.sleep(delai)

    async def _data(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = await self._post(query, variables)
        if body.get("errors"):
            raise DNError("; ".join(e.get("message", "?") for e in body["errors"])[:500])
        return body.get("data") or {}

    # ------------------------------------------------------------------ lecture

    async def catalogue(self, demarche: int) -> list[Label]:
        data = await self._data(Q_CATALOGUE, {"n": demarche})
        return [Label(l["id"], l["name"], l["color"]) for l in data["demarche"]["labels"]]

    async def _pages(self, query: str, variables: dict[str, Any]) -> AsyncIterator[list[DossierLabels]]:
        after = None
        while True:
            data = await self._data(query, {**variables, "after": after})
            conn = data["demarche"]["dossiers"]
            yield [_dossier(n) for n in conn["nodes"]]
            if not conn["pageInfo"]["hasNextPage"]:
                return
            after = conn["pageInfo"]["endCursor"]

    async def dossiers_modifies(self, demarche: int, depuis: datetime) -> list[DossierLabels]:
        """Synchro incrémentale : dossiers modifiés (labels compris) depuis `depuis`."""
        out: list[DossierLabels] = []
        async for page in self._pages(Q_DOSSIERS, {"n": demarche, "since": depuis.isoformat()}):
            out.extend(page)
        return out

    async def tous_les_dossiers(self, demarche: int) -> list[DossierLabels]:
        """Relecture complète, un flux par état en parallèle (dédoublonnée par numéro)."""

        async def flux(etat: str) -> list[DossierLabels]:
            res: list[DossierLabels] = []
            async for page in self._pages(Q_DOSSIERS_ETAT, {"n": demarche, "state": etat}):
                res.extend(page)
            return res

        parts = await asyncio.gather(*(flux(e) for e in ETATS))
        return list({d.numero: d for part in parts for d in part}.values())

    async def dossiers(self, numeros: Sequence[int]) -> list[DossierLabels]:
        """Lecture ciblée par alias (lots de 25, en parallèle). Les numéros introuvables sont ignorés."""

        async def lot(nums: Sequence[int]) -> list[DossierLabels]:
            body = await self._post(_query_lecture_ciblee(len(nums)), {f"n{k}": n for k, n in enumerate(nums)})
            data = body.get("data") or {}
            return [_dossier(node) for k in range(len(nums)) if (node := data.get(f"d{k}"))]

        uniques = list(dict.fromkeys(int(n) for n in numeros))
        parts = await asyncio.gather(*(lot(c) for c in _chunks(uniques, LOT_LECTURE)))
        return [d for part in parts for d in part]

    # ------------------------------------------------------------------ écriture

    async def appliquer(self, action: Action, operations: Sequence[Operation]) -> list[Resultat]:
        """Ajoute ou retire des labels par lots de 50. Un résultat par opération, dans l'ordre."""
        lots = await asyncio.gather(*(self._lot(action, c) for c in _chunks(list(operations), LOT_MUTATION)))
        return [r for lot in lots for r in lot]

    async def _lot(self, action: Action, ops: Sequence[Operation]) -> list[Resultat]:
        variables = {f"i{k}": {"dossierId": op.dossier_id, "labelId": op.label_id} for k, op in enumerate(ops)}
        try:
            body = await self._post(_query_mutation(action, len(ops)), variables)
        except DNError as exc:
            return [Resultat(op, Statut.ERREUR, str(exc)) for op in ops]
        data = body.get("data") or {}
        erreurs_par_alias: dict[str, str] = {}
        for err in body.get("errors") or []:
            path = err.get("path") or []
            if path:
                erreurs_par_alias[str(path[0])] = err.get("message", "erreur")
        resultats = []
        for k, op in enumerate(ops):
            alias = f"m{k}"
            node = data.get(alias)
            if node is None:
                resultats.append(Resultat(op, Statut.ERREUR, erreurs_par_alias.get(alias, "réponse absente")))
                continue
            msgs = [e.get("message", "") for e in node.get("errors") or []]
            dossier = node.get("dossier")
            labels = frozenset(l["id"] for l in dossier.get("labels") or []) if dossier else None
            if not msgs:
                resultats.append(Resultat(op, Statut.APPLIQUE, labels_apres=labels))
            elif all(any(m in msg for m in _DEJA[action]) for msg in msgs):
                resultats.append(Resultat(op, Statut.DEJA_APPLIQUE, msgs[0]))
            else:
                resultats.append(Resultat(op, Statut.ERREUR, "; ".join(msgs)[:300]))
        return resultats


def _message_http(resp: httpx.Response) -> str:
    try:
        errors = resp.json().get("errors") or []
        detail = "; ".join(e.get("message", "") for e in errors)
    except ValueError:
        detail = ""
    if resp.status_code in (401, 403):
        return (f"Accès refusé par DN (HTTP {resp.status_code}) : jeton, démarche ou réseau non autorisé. "
                f"{detail}").strip()
    return f"Erreur DN HTTP {resp.status_code}. {detail}".strip()
