"""Conversion des valeurs Grist ↔ annotations DN, comparaison et affichage.

Valeurs Grist telles que les renvoie `/sql` : Text → str, Int → int, Numeric → float, Bool → 0/1,
Date → secondes epoch (minuit UTC), DateTime → secondes epoch, ChoiceList → JSON `["L", "a", "b"]`.
Une valeur « normalisée » est la forme comparable : str, bool, int, float, date ISO (str),
datetime UTC, tuple de choix ; None = vide.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..dn.annotations import DescripteurAnnotation, Nature

PARIS = ZoneInfo("Europe/Paris")
MAX_TEXTE = 20000


class ValeurInvalide(ValueError):
    pass


def base(type_grist: str) -> str:
    return type_grist.split(":", 1)[0]


def vide(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list | tuple) and not v)


def _liste(v: Any) -> list[str]:
    if isinstance(v, list | tuple):
        items = list(v)
    elif isinstance(v, str) and v.startswith("["):
        try:
            items = json.loads(v)
        except ValueError:
            items = [v]
    elif isinstance(v, str):
        items = v.split(",")
    else:
        items = [v]
    return [str(x).strip() for x in items if x != "L" and not vide(x) and str(x).strip()]


def _nombre(v: Any) -> float:
    if isinstance(v, bool):
        raise ValeurInvalide("nombre attendu")
    if isinstance(v, int | float):
        f = float(v)
    else:
        try:
            f = float(str(v).strip().replace(" ", "").replace(" ", "").replace(",", "."))
        except ValueError:
            raise ValeurInvalide(f"« {str(v)[:40]} » n'est pas un nombre") from None
    if not math.isfinite(f):
        raise ValeurInvalide("nombre invalide")
    return f


def _texte_date(s: str) -> date:
    s = s.strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    try:
        return date(int(m[3]), int(m[2]), int(m[1])) if m else date.fromisoformat(s[:10])
    except ValueError:
        raise ValeurInvalide(f"« {s[:40]} » n'est pas une date (AAAA-MM-JJ ou JJ/MM/AAAA)") from None


def _date(v: Any, type_grist: str) -> date:
    if isinstance(v, int | float) and not isinstance(v, bool):
        if base(type_grist) == "DateTime":
            return datetime.fromtimestamp(v, PARIS).date()
        return datetime.fromtimestamp(v, UTC).date()
    if isinstance(v, str):
        return _texte_date(v)
    raise ValeurInvalide("date attendue")


def _datetime(v: Any, type_grist: str) -> datetime:
    if isinstance(v, int | float) and not isinstance(v, bool):
        if base(type_grist) == "Date":  # une date seule : minuit, heure de Paris
            j = datetime.fromtimestamp(v, UTC).date()
            return datetime(j.year, j.month, j.day, tzinfo=PARIS).astimezone(UTC)
        return datetime.fromtimestamp(v, UTC)
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.strip())
        except ValueError:
            j = _texte_date(v)
            dt = datetime(j.year, j.month, j.day)
        return (dt if dt.tzinfo else dt.replace(tzinfo=PARIS)).astimezone(UTC)
    raise ValeurInvalide("date et heure attendues")


def normaliser(desc: DescripteurAnnotation, v: Any, type_grist: str, *, verifier_options: bool = True) -> Any:
    """Valeur Grist → valeur normalisée. None si vide (à ignorer). Lève ValeurInvalide."""
    if vide(v):
        return None
    n = desc.nature
    if n == Nature.TEXTE:
        if isinstance(v, bool):
            s = "Oui" if v else "Non"
        elif isinstance(v, float) and v.is_integer():
            s = str(int(v))
        elif isinstance(v, int | float) and base(type_grist) in ("Date", "DateTime"):
            s = _date(v, type_grist).isoformat()
        else:
            s = str(v)
        if len(s) > MAX_TEXTE:
            raise ValeurInvalide("texte trop long")
        return s
    if n == Nature.BOOLEEN:
        if isinstance(v, bool | int) and v in (0, 1):
            return bool(v)
        s = str(v).strip().lower()
        if s in ("true", "vrai", "oui", "1", "x"):
            return True
        if s in ("false", "faux", "non", "0"):
            return False
        raise ValeurInvalide(f"« {str(v)[:40]} » n'est pas oui / non")
    if n == Nature.DATE:
        return _date(v, type_grist).isoformat()
    if n == Nature.DATETIME:
        return _datetime(v, type_grist)
    if n == Nature.ENTIER:
        f = _nombre(v)
        if not f.is_integer():
            raise ValeurInvalide(f"{affichage(n, f)} n'est pas un nombre entier")
        return int(f)
    if n == Nature.DECIMAL:
        return _nombre(v)
    if n == Nature.CHOIX:
        s = str(v).strip()
        if verifier_options and not desc.autre_option and s not in desc.options:
            raise ValeurInvalide(f"« {s[:60]} » n'est pas une option de l'annotation dans DN")
        return s
    if n == Nature.CHOIX_MULTIPLES:
        items = tuple(_liste(v))
        if verifier_options and (inconnus := [x for x in items if x not in desc.options]):
            raise ValeurInvalide(f"« {inconnus[0][:60]} » n'est pas une option de l'annotation dans DN")
        return items or None
    raise ValeurInvalide("type d'annotation non pris en charge")  # pragma: no cover


def valeur_dn(desc: DescripteurAnnotation, v: Any) -> Any:
    """Valeur normalisée → valeur à mettre sous la clé `desc.cle` de `AnnotationValueInput`."""
    if desc.nature == Nature.DATETIME:
        return v.isoformat()
    if desc.nature == Nature.CHOIX_MULTIPLES:
        return list(v)
    return v


def egales(nature: Nature, a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if nature in (Nature.DECIMAL, Nature.ENTIER):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    if nature == Nature.CHOIX_MULTIPLES:
        return sorted(a) == sorted(b)
    if nature == Nature.TEXTE:
        return str(a).strip() == str(b).strip()
    return a == b


def vers_grist(nature: Nature, v: Any, type_grist: str) -> Any:
    """Valeur normalisée → cellule Grist (copie OTP mise à jour après envoi)."""
    t = base(type_grist)
    if v is None:
        return None
    if nature == Nature.DATE and t in ("Date", "DateTime"):
        j = date.fromisoformat(v)
        return datetime(j.year, j.month, j.day, tzinfo=UTC).timestamp()
    if nature == Nature.DATETIME and t in ("Date", "DateTime"):
        return v.timestamp()
    if nature == Nature.CHOIX_MULTIPLES:
        return ", ".join(v)
    if t == "Text" and not isinstance(v, str):
        return affichage(nature, v)
    return v


def affichage(nature: Nature, v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Oui" if v else "Non"
    if nature == Nature.DATE:
        try:
            return date.fromisoformat(v).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, datetime):
        return v.astimezone(PARIS).strftime("%d/%m/%Y %H:%M")
    if isinstance(v, float):
        return (str(int(v)) if v.is_integer() else f"{v}").replace(".", ",")
    if isinstance(v, tuple | list):
        return ", ".join(v)
    return str(v)


# ------------------------------------------------------------------ compatibilité des types

OK, AVERTISSEMENT, ERREUR = "ok", "avertissement", "erreur"

_COMPAT: dict[Nature, dict[str, tuple[str, str]]] = {
    Nature.TEXTE: {t: (OK, "") for t in ("Text", "Choice", "Any", "Int", "Numeric", "Date", "DateTime")},
    Nature.BOOLEEN: {"Bool": (OK, ""), "Text": (AVERTISSEMENT, "valeurs attendues : oui / non")},
    Nature.DATE: {"Date": (OK, ""), "DateTime": (AVERTISSEMENT, "l'heure sera ignorée"),
                  "Text": (AVERTISSEMENT, "texte au format AAAA-MM-JJ ou JJ/MM/AAAA"),
                  "Any": (AVERTISSEMENT, "texte au format AAAA-MM-JJ ou JJ/MM/AAAA")},
    Nature.DATETIME: {"DateTime": (OK, ""), "Date": (AVERTISSEMENT, "envoyée à minuit, heure de Paris")},
    Nature.ENTIER: {"Int": (OK, ""), "Numeric": (AVERTISSEMENT, "les valeurs non entières seront refusées"),
                    "Text": (AVERTISSEMENT, "les textes non numériques seront refusés"),
                    "Any": (AVERTISSEMENT, "les valeurs non entières seront refusées")},
    Nature.DECIMAL: {"Numeric": (OK, ""), "Int": (OK, ""),
                     "Text": (AVERTISSEMENT, "les textes non numériques seront refusés"),
                     "Any": (AVERTISSEMENT, "les valeurs non numériques seront refusées")},
    Nature.CHOIX: {t: (OK, "") for t in ("Text", "Choice", "Any")},
    Nature.CHOIX_MULTIPLES: {t: (OK, "") for t in ("ChoiceList", "Choice", "Text", "Any")},
}


def compatibilite(desc: DescripteurAnnotation, type_grist: str) -> tuple[str, str]:
    niveau, msg = _COMPAT[desc.nature].get(base(type_grist), (ERREUR, ""))
    if niveau == ERREUR:
        return ERREUR, f"Types incompatibles : colonne {base(type_grist)} vers {desc.type_libelle}"
    return niveau, msg
