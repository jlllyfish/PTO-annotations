"""Routes des règles automatiques (widget, jeton Grist de l'utilisateur)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request

from ..regles import service
from ..regles.moteur import DefinitionRegle, RegleInvalide, champs_disponibles, schema_public, valeurs_proposees
from .routes import Qui, client_dn, demarche_de, exiger_proprietaire, grist_de

router = APIRouter(prefix="/api/demarches/{numero}/regles")
Num = Annotated[int, Path(gt=0)]
Id = Annotated[int, Path(gt=0)]


def _verifier_mode(request: Request, regle: DefinitionRegle) -> None:
    if regle.mode == "auto" and not request.app.state.config.regles_auto_autorisees:
        raise HTTPException(403, "Le mode automatique est désactivé dans la configuration du serveur")


def _cle(request: Request) -> bytes:
    return request.app.state.cle_regles


def _erreur(exc: RegleInvalide) -> HTTPException:
    return HTTPException(422, str(exc))


@router.get("/schema")
async def schema(request: Request, qui: Qui, numero: Num) -> dict:
    d = demarche_de(qui, numero)
    async with grist_de(request, qui) as grist:
        return {**schema_public(await champs_disponibles(grist, d)),
                "auto_autorise": request.app.state.config.regles_auto_autorisees}


@router.get("/valeurs")
async def valeurs(request: Request, qui: Qui, numero: Num,
                  champ: Annotated[str, Query(min_length=1, max_length=210)]) -> dict:
    d = demarche_de(qui, numero)
    await exiger_proprietaire(request, qui, d)  # valeurs lues par la clé de service : réservé aux propriétaires
    try:
        async with grist_de(request, qui) as grist:
            return await valeurs_proposees(grist, d, await champs_disponibles(grist, d), champ)
    except RegleInvalide as exc:
        raise _erreur(exc) from None


@router.get("")
async def lister(request: Request, qui: Qui, numero: Num) -> dict:
    d = demarche_de(qui, numero)
    async with grist_de(request, qui) as grist:
        return {"regles": await service.lister(grist, d, cle_schema=qui.document.grist_doc_id, cle=_cle(request))}


@router.post("", status_code=201)
async def creer(request: Request, qui: Qui, numero: Num, regle: DefinitionRegle) -> dict:
    d = demarche_de(qui, numero)
    _verifier_mode(request, regle)
    await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            rid = await service.enregistrer(client_dn(request, d), grist, d, regle,
                                            cle_schema=qui.document.grist_doc_id, cle=_cle(request))
    except RegleInvalide as exc:
        raise _erreur(exc) from None
    return {"id": rid}


@router.put("/{regle_id}")
async def modifier(request: Request, qui: Qui, numero: Num, regle_id: Id, regle: DefinitionRegle) -> dict:
    d = demarche_de(qui, numero)
    _verifier_mode(request, regle)
    await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            await service.enregistrer(client_dn(request, d), grist, d, regle,
                                      cle_schema=qui.document.grist_doc_id, regle_id=regle_id, cle=_cle(request))
    except RegleInvalide as exc:
        raise _erreur(exc) from None
    return {"id": regle_id}


@router.delete("/{regle_id}")
async def supprimer(request: Request, qui: Qui, numero: Num, regle_id: Id) -> dict:
    d = demarche_de(qui, numero)
    await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            await service.supprimer(grist, d, regle_id)
    except RegleInvalide as exc:
        raise _erreur(exc) from None
    return {"supprimee": regle_id}


@router.post("/simuler")
async def simuler(request: Request, qui: Qui, numero: Num, regle: DefinitionRegle,
                  regle_id: Annotated[int | None, Query(gt=0)] = None) -> dict:
    """Aperçu sans écriture : quels dossiers la règle toucherait maintenant."""
    d = demarche_de(qui, numero)
    await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            ev = await service.evaluer(grist, d, regle, cle_schema=qui.document.grist_doc_id, regle_id=regle_id)
    except RegleInvalide as exc:
        raise _erreur(exc) from None
    ev.pop("_a_faire", None)
    return ev


@router.post("/{regle_id}/appliquer")
async def appliquer(request: Request, qui: Qui, numero: Num, regle_id: Id) -> dict:
    d = demarche_de(qui, numero)
    droits = await exiger_proprietaire(request, qui, d)
    try:
        async with grist_de(request, qui) as grist:
            bilan = await service.appliquer(client_dn(request, d), grist, d, regle_id,
                                            cle_schema=qui.document.grist_doc_id, cle=_cle(request),
                                            auteur=droits.identite.email)
    except RegleInvalide as exc:
        raise _erreur(exc) from None
    if bilan is None:
        return {"bilan": None}
    b = asdict(bilan)
    b.pop("statuts", None)
    return {"bilan": b}
