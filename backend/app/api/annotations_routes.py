"""Routes de l'onglet « Annotations » : correspondances, aperçu, envoi vers les annotations privées DN."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..annotations.service import (
    CorrespondanceInvalide,
    SansInstructeur,
    apercu,
    enregistrer_correspondances,
    envoyer_file,
    executer,
    instructeur_de,
    mettre_en_file,
    vue_correspondances,
)
from ..config import DemarcheConfig
from ..droits import Droits
from .routes import Qui, client_dn, demarche_de, droits_de, exiger_action, exiger_proprietaire, grist_de

router = APIRouter()

Num = Annotated[int, Path(gt=0)]
AnnotationId = Annotated[str, Field(pattern=r"^[A-Za-z0-9+/=_-]{4,64}$")]
Ref = Annotated[str, Field(pattern=r"^[dca]\.[A-Za-z_][A-Za-z0-9_]{0,99}$")]
Numeros = Annotated[list[Annotated[int, Field(gt=0)]], Field(min_length=1, max_length=500)]


class DemandeCorrespondances(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correspondances: Annotated[dict[AnnotationId, Ref | None], Field(max_length=200)]


class Cible(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: Annotated[int, Field(gt=0)]
    annotation_id: AnnotationId


class DemandeApercu(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numeros: Numeros
    annotation_ids: Annotated[list[AnnotationId], Field(max_length=200)] | None = None  # None : toutes


class DemandeEnvoi(DemandeApercu):
    ecraser_tout: bool = False                                        # écraser les annotations modifiées dans DN
    ecraser: Annotated[list[Cible], Field(max_length=500)] = []       # … ou seulement celles-ci
    envoyer: bool = True                                              # False : mettre en file sans envoyer


async def _instructeur(request: Request, d: DemarcheConfig, droits: Droits) -> str:
    groupes = await request.app.state.groupes.groupes(client_dn(request, d), d)
    try:
        return instructeur_de(groupes, droits.identite.email)
    except SansInstructeur as exc:
        raise HTTPException(403, str(exc)) from None


@router.get("/api/demarches/{numero}/annotations/correspondances")
async def route_correspondances(request: Request, qui: Qui, numero: Num,
                                frais: Annotated[bool, Query()] = False) -> dict:
    d = demarche_de(qui, numero)
    droits = await droits_de(request, qui, d)
    if not (droits.peut_agir or droits.proprietaire):
        raise HTTPException(403, droits.raison_refus() or "Action non autorisée")
    async with grist_de(request, qui) as grist:
        vue = await vue_correspondances(client_dn(request, d), grist, d, cle_schema=qui.document.grist_doc_id,
                                        frais=frais)
    return {**vue, "modifiable": droits.proprietaire}


@router.put("/api/demarches/{numero}/annotations/correspondances")
async def route_enregistrer(request: Request, qui: Qui, numero: Num, demande: DemandeCorrespondances) -> dict:
    d = demarche_de(qui, numero)
    droits = await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            n = await enregistrer_correspondances(client_dn(request, d), grist, d, demande.correspondances,
                                                  cle_schema=qui.document.grist_doc_id, auteur=droits.identite.email)
    except CorrespondanceInvalide as exc:
        raise HTTPException(422, str(exc)) from None
    return {"enregistrees": n}


@router.post("/api/demarches/{numero}/annotations/apercu")
async def route_apercu(request: Request, qui: Qui, numero: Num, demande: DemandeApercu) -> dict:
    d = demarche_de(qui, numero)
    droits = await exiger_action(request, qui, d)
    async with grist_de(request, qui) as grist:
        return await apercu(client_dn(request, d), grist, d, demande.numeros, demande.annotation_ids,
                            cle_schema=qui.document.grist_doc_id, perimetre=droits.perimetre)


@router.post("/api/demarches/{numero}/annotations/envoyer")
async def route_envoyer(request: Request, qui: Qui, numero: Num, demande: DemandeEnvoi) -> dict:
    d = demarche_de(qui, numero)
    droits = await exiger_action(request, qui, d)
    dn = client_dn(request, d)
    cibles = dict.fromkeys(dict.fromkeys(demande.numeros), demande.annotation_ids)
    ecraser = {(c.numero, c.annotation_id) for c in demande.ecraser}
    commun = {"cle_schema": qui.document.grist_doc_id, "ecraser_tout": demande.ecraser_tout, "ecraser": ecraser,
              "perimetre": droits.perimetre, "auteur": droits.identite.email}
    async with grist_de(request, qui) as grist:
        if demande.envoyer:
            instructeur = await _instructeur(request, d, droits)
            bilan = await executer(dn, grist, d, cibles, instructeur_id=instructeur, source="manuel", **commun)
        else:
            bilan = await mettre_en_file(dn, grist, d, cibles, **commun)
    return asdict(bilan)


@router.post("/api/demarches/{numero}/annotations/file/envoyer")
async def route_envoyer_file(request: Request, qui: Qui, numero: Num) -> dict:
    d = demarche_de(qui, numero)
    droits = await exiger_action(request, qui, d)
    instructeur = await _instructeur(request, d, droits)
    async with grist_de(request, qui) as grist:
        bilan = await envoyer_file(client_dn(request, d), grist, d, instructeur_id=instructeur,
                                   cle_schema=qui.document.grist_doc_id, perimetre=droits.perimetre,
                                   auteur=droits.identite.email)
    return asdict(bilan)
