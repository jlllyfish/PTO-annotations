"""Routes d'ajout / retrait de labels (appelées par le widget, avec le jeton Grist de l'utilisateur)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from ..dn.client import Action
from ..ops.service import LabelInconnu, apercu, envoyer_file, executer, mettre_en_file
from .routes import Qui, client_dn, demarche_de

router = APIRouter()

LabelId = Annotated[str, Field(pattern=r"^[A-Za-z0-9+/=_-]{4,64}$")]
Numeros = Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=500)]


class DemandeApercu(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    label_id: LabelId
    numeros: Numeros


class DemandeOperations(DemandeApercu):
    envoyer: bool = True  # False : mettre en file sans envoyer


Num = Annotated[int, Path(gt=0)]


@router.post("/api/demarches/{numero}/operations/apercu")
async def route_apercu(request: Request, qui: Qui, numero: Num, demande: DemandeApercu) -> dict:
    d = demarche_de(qui, numero)
    try:
        return await apercu(client_dn(request, d), d, demande.action, demande.label_id, demande.numeros)
    except LabelInconnu as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/api/demarches/{numero}/operations")
async def route_operations(request: Request, qui: Qui, numero: Num, demande: DemandeOperations) -> dict:
    d = demarche_de(qui, numero)
    dn = client_dn(request, d)
    doc = qui.document.grist_doc_id
    try:
        async with qui.grist(request.app.state.grist_transport) as grist:
            if demande.envoyer:
                bilan = await executer(dn, grist, d, demande.action, demande.label_id, demande.numeros,
                                       source="manuel", cle_schema=doc)
            else:
                bilan = await mettre_en_file(dn, grist, d, demande.action, demande.label_id, demande.numeros,
                                             source="manuel", cle_schema=doc)
    except LabelInconnu as exc:
        raise HTTPException(422, str(exc)) from None
    return asdict(bilan)


@router.post("/api/demarches/{numero}/operations/file/envoyer")
async def route_envoyer_file(request: Request, qui: Qui, numero: Num) -> dict:
    d = demarche_de(qui, numero)
    async with qui.grist(request.app.state.grist_transport) as grist:
        bilans = await envoyer_file(client_dn(request, d), grist, d, cle_schema=qui.document.grist_doc_id)
    return {"lots": [asdict(b) for b in bilans]}
