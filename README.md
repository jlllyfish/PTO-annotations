# Labels DN ↔ Grist

Gérer les labels des dossiers **Démarche Numérique** depuis un document **Grist** synchronisé par
[OTP](https://github.com/betagouv/OTP-DS-to-Grist) : widget DSFR, ajout/retrait unitaire ou en masse,
règles automatiques ET/OU, synchronisation incrémentale.

| Dossier | Contenu |
|---|---|
| `backend/` | API FastAPI + service du widget (phase 1 : socle) |
| `spikes/` | Scripts de vérification de la phase 0 et leur fiche de résultats (`RESULTATS.md`) |

## Lancer le backend en local (PowerShell)

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item demarches.example.yaml demarches.yaml   # puis adapter
Copy-Item .env.example .env                       # puis renseigner les jetons
Get-Content .env | ForEach-Object { if ($_ -match '^([A-Z_]+)=(.+)$') { Set-Item "env:$($Matches[1])" $Matches[2] } }
$env:LBL_CONFIG = "demarches.yaml"
uvicorn app.main:create_app --factory --port 8000
```

- `http://localhost:8000/health` → `{"ok": true}`
- Widget : vue personnalisée Grist d'URL `http://localhost:8000/widget/`, **accès complet au document**.

Ou avec Docker : `docker compose up --build` (mêmes fichiers `demarches.yaml` et `.env`).

## Qualité et sécurité

```powershell
pytest -q                                  # tests (DN et Grist simulés)
ruff check .                               # style et règles de sécurité
bandit -q -c pyproject.toml -r app         # analyse statique de sécurité
pip-audit -r requirements.txt              # vulnérabilités connues des dépendances
```

La CI GitHub (`.github/workflows/ci.yml`) lance les quatre à chaque push.

## Principes de sécurité

- **Aucun proxy GraphQL** : l'API n'expose que des routes métier ; toutes les valeurs passent
  en `variables` GraphQL ou en paramètres SQL ; les identifiants de tables/colonnes sont validés.
- **Authentification du widget** par jeton d'accès Grist, vérifié auprès de Grist, limité aux
  documents déclarés dans `demarches.yaml` (contrôle fait avant tout appel réseau).
- **Secrets** hors du code et du YAML (variables `NOM` ou fichiers `NOM_FILE`) ; démarrage refusé s'il en manque ;
  jamais journalisés (les journaux d'URL de httpx sont coupés car le jeton Grist y figure).
- **Jetons DN au moindre privilège** : un par démarche si possible, restreint à l'IP du serveur.
- **En-têtes stricts** : CSP sans `unsafe-inline` (`unsafe-eval` uniquement pour le widget, exigé par
  `grist-plugin-api.js`), `frame-ancestors` limité à l'instance Grist, HSTS, `nosniff`, `no-referrer`.
- **Garde-fous** : taille de requête bornée, limitation de débit par document, concurrence DN bornée
  avec nouvelles tentatives sur 429/5xx, conteneur non root en lecture seule.
