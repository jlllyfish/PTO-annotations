"""Routes HTTP de base (phase 1). Les routes métier arrivent en phases 2 à 5."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request

from ..config import DemarcheConfig, read_secret
from ..dn.client import DNClient
from ..droits import Droits, calculer
from ..grist.client import GristClient
from ..identite import IdentiteDouteuse
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


def grist_de(request: Request, qui: Appelant) -> GristClient:
    """Client Grist de l'utilisateur (écritures sous ses droits) ; lectures SQL par la clé de service."""
    state = request.app.state
    client = qui.grist(state.grist_transport)
    client.lecteur = GristClient.par_cle(state.config.grist_host, qui.document.grist_doc_id,
                                         read_secret(state.config.grist_service_key), transport=state.grist_transport)
    return client


def client_dn(request: Request, demarche: DemarcheConfig) -> DNClient:
    return request.app.state.dn_clients(demarche.dn_token)


async def identite_de(request: Request, qui: Appelant):
    try:
        return await request.app.state.identification.identifier(qui)
    except IdentiteDouteuse as exc:
        raise HTTPException(403, f"Identité non vérifiable : {exc}") from None


async def droits_de(request: Request, qui: Appelant, d: DemarcheConfig) -> Droits:
    identite = await identite_de(request, qui)
    return await calculer(identite, client_dn(request, d), d, request.app.state.groupes)


async def exiger_action(request: Request, qui: Appelant, d: DemarcheConfig) -> Droits:
    droits = await droits_de(request, qui, d)
    if not droits.peut_agir:
        raise HTTPException(403, droits.raison_refus() or "Action non autorisée")
    return droits


async def exiger_proprietaire(request: Request, qui: Appelant, d: DemarcheConfig) -> Droits:
    droits = await droits_de(request, qui, d)
    if not droits.proprietaire:
        raise HTTPException(403, "Réservé aux propriétaires du document Grist")
    return droits


@router.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/api/contexte")
async def contexte(request: Request, qui: Qui) -> dict:
    doc = qui.document
    return {
        "document": {"id": doc.grist_doc_id, "nom": doc.nom},
        "demarches": [{"numero": d.numero, "nom": d.nom, "table": d.table} for d in doc.demarches],
        "journal_retention_jours": request.app.state.config.journal_retention_jours,
    }


@router.get("/api/demarches/{numero}/droits")
async def droits(request: Request, qui: Qui, numero: Annotated[int, Path(gt=0)]) -> dict:
    """Qui est connecté (certifié par Grist), ses groupes instructeurs DN, ce qu'il peut faire."""
    d = demarche_de(qui, numero)
    return (await droits_de(request, qui, d)).vue()


@router.get("/api/demarches/{numero}/catalogue")
async def catalogue(request: Request, qui: Qui, numero: Annotated[int, Path(gt=0)]) -> dict:
    d = demarche_de(qui, numero)
    labels = await client_dn(request, d).catalogue(d.numero)
    return {"demarche": d.numero, "labels": [{"id": l.id, "nom": l.nom, "couleur": l.couleur} for l in labels]}
