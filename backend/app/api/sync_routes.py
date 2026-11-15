"""Routes de synchronisation : depuis le widget (jeton de l'utilisateur) et depuis n8n (secret partagé)."""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import read_secret
from ..grist.client import GristClient
from ..ops.service import vidange_automatique
from ..regles.service import appliquer_regles_auto
from ..sync.jobs import DejaEnCours
from ..sync.service import Mode, Progression, lire_etat, synchroniser
from .routes import Qui, client_dn, demarche_de

router = APIRouter()


class DemandeSynchro(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Mode = Mode.INCREMENTALE
    numeros: list[Annotated[int, Field(gt=0)]] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _coherence(self) -> DemandeSynchro:
        if (self.mode == Mode.CIBLEE) != bool(self.numeros):
            raise ValueError("« numeros » est requis pour le mode ciblee, et seulement pour lui")
        return self


@router.post("/api/demarches/{numero}/synchro", status_code=202)
async def lancer_synchro(request: Request, qui: Qui, numero: Annotated[int, Path(gt=0)],
                         demande: DemandeSynchro) -> dict:
    d = demarche_de(qui, numero)
    app = request.app.state
    dn = client_dn(request, d)
    doc_id = qui.document.grist_doc_id

    async def travail(prog: Progression):
        async with qui.grist(app.grist_transport) as grist:
            return await synchroniser(dn, grist, d, demande.mode, cle_schema=doc_id,
                                      numeros=demande.numeros, progression=prog)

    try:
        tache = app.taches.lancer(doc_id, numero, demande.mode, "widget", travail)
    except DejaEnCours as exc:
        raise HTTPException(409, str(exc)) from None
    return {"tache": tache.vue()}


@router.get("/api/demarches/{numero}/synchro")
async def etat_synchro(request: Request, qui: Qui, numero: Annotated[int, Path(gt=0)]) -> dict:
    d = demarche_de(qui, numero)
    tache = request.app.state.taches.etat(qui.document.grist_doc_id, numero)
    async with qui.grist(request.app.state.grist_transport) as grist:
        tables = await grist.tables()
        derniere = await lire_etat(grist, d.numero) if "LBL_Etat" in tables else None
    return {"tache": tache.vue() if tache else None, "derniere": derniere}


@router.post("/api/taches/synchro")
async def tache_planifiee(
    request: Request,
    mode: Annotated[Literal["incrementale", "complete"], Query()] = "incrementale",
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """Déclenchée par n8n (cron) avec le secret partagé ; utilise la clé Grist du compte de service."""
    cfg = request.app.state.config
    if not cfg.task_token:
        raise HTTPException(404, "Not Found")
    attendu = f"Bearer {read_secret(cfg.task_token)}"
    if not authorization or not hmac.compare_digest(authorization.encode(), attendu.encode()):
        raise HTTPException(401, "Secret de tâche invalide")

    cle = read_secret(cfg.grist_service_key)
    resultats = []
    for doc in cfg.documents:
        for d in doc.demarches:
            dn = client_dn(request, d)

            async def travail(prog: Progression, doc=doc, d=d, dn=dn):
                async with GristClient.par_cle(cfg.grist_host, doc.grist_doc_id, cle,
                                               transport=request.app.state.grist_transport) as grist:
                    bilan = await synchroniser(dn, grist, d, Mode(mode), cle_schema=doc.grist_doc_id, progression=prog)
                    if cfg.regles_auto_autorisees:
                        bilan.regles = await appliquer_regles_auto(dn, grist, d, cle_schema=doc.grist_doc_id)
                    bilan.journal_purge = await vidange_automatique(
                        grist, d, cfg.journal_retention_jours, cle_schema=doc.grist_doc_id)
                    return bilan

            try:
                tache = await request.app.state.taches.executer(
                    doc.grist_doc_id, d.numero, Mode(mode), "tache_planifiee", travail
                )
                resultats.append({"document": doc.grist_doc_id, "demarche": d.numero, **tache.vue()})
            except DejaEnCours as exc:
                resultats.append({"document": doc.grist_doc_id, "demarche": d.numero, "statut": "ignoree",
                                  "erreur": str(exc)})
    erreurs = sum(1 for r in resultats if r.get("statut") == "erreur")
    return {"ok": erreurs == 0, "erreurs": erreurs, "resultats": resultats}
