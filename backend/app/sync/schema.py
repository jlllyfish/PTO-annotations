"""Tables propres à l'outil (préfixe LBL_), créées ou complétées si besoin.

On ne modifie jamais le schéma des tables d'OTP : on y met seulement à jour
`label_names` / `labels_json`, au format exact d'OTP.
"""

from __future__ import annotations

from typing import Any

from ..grist.client import GristClient, GristError

DT = "DateTime:Europe/Paris"

# Formules déclenchées de LBL_Sessions : Grist les calcule avec l'identité de CELUI QUI ÉCRIT la ligne.
# Chaque colonne dépend d'elle-même : toute valeur forcée (à la création ou après) est recalculée (vérifié en spike).
TRIGGERS_SESSIONS = {"email": "user.Email", "user_id": "user.UserID", "acces": "user.Access", "nom": "user.Name"}


def _trigger(formule: str) -> dict[str, Any]:
    return {"type": "Any", "isFormula": False, "formula": formule, "recalcWhen": 0}


TABLES: dict[str, list[tuple[str, str | dict[str, Any]]]] = {
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
        ("cree_le", DT), ("traite_le", DT), ("auteur", "Text"),
    ],
    # Règles automatiques : conditions = groupes OU de conditions ET, en JSON validé par le serveur
    "LBL_Regles": [
        ("demarche", "Int"), ("nom", "Text"), ("action", "Text"), ("label_id", "Text"), ("label", "Text"),
        ("mode", "Text"), ("verrou", "Bool"), ("conditions", "Text"),
        ("modifie_le", DT), ("derniere_execution", DT), ("dernier_resultat", "Text"),
        ("signature", "Text"),  # HMAC du serveur : une règle modifiée directement dans Grist n'est plus exécutée
    ],
    # Dossiers déjà traités par chaque règle (pour ne pas refaire ce qu'une personne a défait)
    "LBL_Regles_Traces": [("regle", "Int"), ("dossier_number", "Text")],
    # Sondes d'identité (une ligne éphémère par vérification ; supprimée aussitôt lue)
    "LBL_Sessions": [("jeton", "Text"), ("cree_le", DT)] + [(c, _trigger(f)) for c, f in TRIGGERS_SESSIONS.items()],
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
    await reparer_triggers(grist)
    _deja_verifie.add(cle_cache)


def _deps(v: Any) -> list[int]:
    return [int(x) for x in v[1:]] if isinstance(v, list) and v[:1] == ["L"] else []


def triggers_conformes(colonnes: list) -> bool:
    """Les formules de LBL_Sessions sont-elles exactement celles attendues (personne ne les a modifiées) ?"""
    par_id = {c.id: c for c in colonnes}
    for col, formule in TRIGGERS_SESSIONS.items():
        c = par_id.get(col)
        if c is None:
            return False
        m = c.meta
        if (m.get("formula") != formule or m.get("isFormula") is not False or m.get("recalcWhen") not in (0, None)
                or _deps(m.get("recalcDeps")) != [m.get("colRef")]):
            return False
    return True


async def reparer_triggers(grist: GristClient) -> None:
    """Remet les formules de LBL_Sessions dans l'état attendu (formule + dépendance à elle-même)."""
    cols = {c.id: c for c in await grist.colonnes("LBL_Sessions")}
    corrections = []
    for col, formule in TRIGGERS_SESSIONS.items():
        if col not in cols:
            continue
        m = cols[col].meta
        attendu = {**_trigger(formule), "recalcDeps": ["L", m.get("colRef")]}
        if (m.get("formula") != formule or m.get("isFormula") is not False or m.get("recalcWhen") not in (0, None)
                or _deps(m.get("recalcDeps")) != [m.get("colRef")]):
            corrections.append({"id": col, "fields": attendu})
    if corrections:
        await grist.maj_colonnes("LBL_Sessions", corrections)


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
