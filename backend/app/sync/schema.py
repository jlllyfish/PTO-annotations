"""Tables propres à l'outil (préfixe LBL_), créées ou complétées si besoin.

On ne modifie jamais le schéma des tables d'OTP : on y met seulement à jour
`label_names` / `labels_json`, au format exact d'OTP.
"""

from __future__ import annotations

from ..grist.client import GristClient, GristError

DT = "DateTime:Europe/Paris"

TABLES: dict[str, list[tuple[str, str]]] = {
    "LBL_Catalogue": [
        ("demarche", "Int"), ("label_id", "Text"), ("nom", "Text"), ("couleur", "Text"), ("actif", "Bool"),
    ],
    "LBL_Etat": [
        ("demarche", "Int"), ("mode", "Text"), ("statut", "Text"), ("message", "Text"),
        ("debut", DT), ("fin", DT), ("duree_s", "Numeric"),
        ("dossiers_lus", "Int"), ("dossiers_maj", "Int"), ("absents_grist", "Int"),
        # Début de la dernière synchro réussie (incrémentale ou complète) : point de départ de la suivante.
        ("curseur", DT), ("derniere_complete", DT),
    ],
    # File d'attente ET journal : une ligne par (dossier, label, action)
    "LBL_Operations": [
        ("demarche", "Int"), ("dossier_number", "Text"), ("label_id", "Text"), ("label", "Text"),
        ("action", "Text"), ("source", "Text"), ("statut", "Text"), ("message", "Text"),
        ("cree_le", DT), ("traite_le", DT),
    ],
}

# Colonnes OTP indispensables dans Demarche_<n>_dossiers
COLONNES_OTP = {"dossier_number", "label_names", "labels_json"}

_deja_verifie: set[str] = set()


async def assurer_schema(grist: GristClient, cle_cache: str) -> None:
    """Crée les tables LBL_ manquantes et leurs colonnes manquantes (une fois par document et par processus)."""
    if cle_cache in _deja_verifie:
        return
    existantes = set(await grist.tables())
    for table, colonnes in TABLES.items():
        if table not in existantes:
            await grist.creer_table(table, colonnes)
            continue
        presentes = {c.id for c in await grist.colonnes(table)}
        manquantes = [(c, t) for c, t in colonnes if c not in presentes]
        if manquantes:
            await grist.ajouter_colonnes(table, manquantes)
    _deja_verifie.add(cle_cache)


async def verifier_table_otp(grist: GristClient, table: str) -> None:
    try:
        presentes = {c.id for c in await grist.colonnes(table)}
    except GristError as exc:
        if exc.status == 404:
            msg = f"Table {table} absente : lancez d'abord la synchro OTP de cette démarche"
            raise GristError(msg, status=404) from None
        raise
    if manquantes := COLONNES_OTP - presentes:
        raise GristError(f"Colonnes OTP manquantes dans {table} : {', '.join(sorted(manquantes))}", status=409)
