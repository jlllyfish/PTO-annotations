"""Configuration : fichier `demarches.yaml` (fonctionnel) + secrets (environnement ou fichiers).

Le YAML ne contient AUCUN secret : uniquement le NOM des variables qui les portent.
Un secret `NOM` est lu dans la variable d'environnement `NOM`, ou dans le fichier
indiqué par `NOM_FILE` (secrets Docker / systemd). Le démarrage échoue si un secret manque.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

DOC_ID_RE = r"^[A-Za-z0-9]{10,64}$"
ENV_NAME_RE = r"^[A-Z][A-Z0-9_]{2,63}$"
TABLE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")


class ConfigError(RuntimeError):
    pass


def read_secret(name: str) -> str:
    value = os.getenv(name)
    if not value and (path := os.getenv(f"{name}_FILE")):
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"Secret {name} : fichier illisible ({exc.__class__.__name__})") from None
    if not value:
        raise ConfigError(f"Secret manquant : {name} (variable {name} ou {name}_FILE)")
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DemarcheConfig(_Strict):
    numero: int = Field(gt=0)
    nom: str = Field(min_length=1, max_length=200)
    dn_token: str = Field(pattern=ENV_NAME_RE, description="Nom de la variable portant le jeton DN")
    table_dossiers: str | None = None

    @field_validator("table_dossiers")
    @classmethod
    def _table(cls, v: str | None) -> str | None:
        if v is not None and not TABLE_ID_RE.fullmatch(v):
            raise ValueError("identifiant de table Grist invalide")
        return v

    @property
    def table(self) -> str:
        """Table des dossiers créée par OTP."""
        return self.table_dossiers or f"Demarche_{self.numero}_dossiers"

    def table_otp(self, suffixe: str) -> str:
        return f"Demarche_{self.numero}_{suffixe}"


class DocumentConfig(_Strict):
    grist_doc_id: str = Field(pattern=DOC_ID_RE)
    nom: str = Field(min_length=1, max_length=200)
    demarches: list[DemarcheConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> DocumentConfig:
        nums = [d.numero for d in self.demarches]
        if len(nums) != len(set(nums)):
            raise ValueError(f"démarche en double dans le document {self.grist_doc_id}")
        return self

    def demarche(self, numero: int) -> DemarcheConfig | None:
        return next((d for d in self.demarches if d.numero == numero), None)


class AppConfig(_Strict):
    grist_host: str = Field(default="grist.numerique.gouv.fr", pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$")
    grist_service_key: str = Field(default="GRIST_SERVICE_KEY", pattern=ENV_NAME_RE)
    dn_api_url: HttpUrl = HttpUrl("https://demarche.numerique.gouv.fr/api/v2/graphql")
    dn_concurrence: int = Field(default=4, ge=1, le=8)
    # Secret partagé avec n8n pour déclencher les tâches de fond (route désactivée si absent)
    task_token: str | None = Field(default=None, pattern=ENV_NAME_RE)
    documents: list[DocumentConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_docs(self) -> AppConfig:
        ids = [d.grist_doc_id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("document Grist en double")
        if self.dn_api_url.scheme != "https":
            raise ValueError("dn_api_url doit être en https")
        return self

    def document(self, doc_id: str) -> DocumentConfig | None:
        return next((d for d in self.documents if d.grist_doc_id == doc_id), None)

    def secrets_requis(self) -> set[str]:
        noms = {self.grist_service_key} | {d.dn_token for doc in self.documents for d in doc.demarches}
        return noms | ({self.task_token} if self.task_token else set())


def load_config(path: str | Path, *, verifier_secrets: bool = True) -> AppConfig:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Lecture de {path} impossible : {exc}") from None
    try:
        cfg = AppConfig.model_validate(raw or {})
    except ValueError as exc:
        raise ConfigError(f"Configuration invalide :\n{exc}") from None
    if verifier_secrets:
        for name in sorted(cfg.secrets_requis()):
            read_secret(name)
    return cfg


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config(os.getenv("LBL_CONFIG", "demarches.yaml"))
