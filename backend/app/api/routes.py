"""Routes HTTP de base (phase 1). Les routes métier arrivent en phases 2 à 5."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request

from ..config import DemarcheConfig
from ..dn.client import DNClient
from ..security import Appelant, AuthError

router = APIRouter()


async def appelant(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_grist_base_url: Annotated[str | None, Header()] = None,
) -> Appelant:
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    state = request.app.state
    try:
        qui = await state.verificateur.verifier(token, x_grist_base_url)
        state.limiteur.verifier(qui.document.grist_doc_id)
    except AuthError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return qui


Qui = Annotated[Appelant, Depends(appelant)]


def demarche_de(qui: Appelant, numero: int) -> DemarcheConfig:
    d = qui.document.demarche(numero)
    if d is None:
        raise HTTPException(404, "Démarche non configurée pour ce document")
    return d


def client_dn(request: Request, demarche: DemarcheConfig) -> DNClient:
    return request.app.state.dn_clients(demarche.dn_token)


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/api/contexte")
async def contexte(qui: Qui) -> dict:
    doc = qui.document
    return {
        "document": {"id": doc.grist_doc_id, "nom": doc.nom},
        "demarches": [{"numero": d.numero, "nom": d.nom, "table": d.table} for d in doc.demarches],
    }


@router.get("/api/demarches/{numero}/catalogue")
async def catalogue(request: Request, qui: Qui, numero: Annotated[int, Path(gt=0)]) -> dict:
    d = demarche_de(qui, numero)
    labels = await client_dn(request, d).catalogue(d.numero)
    return {"demarche": d.numero, "labels": [{"id": l.id, "nom": l.nom, "couleur": l.couleur} for l in labels]}
