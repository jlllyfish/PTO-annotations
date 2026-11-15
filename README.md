# PTO-labels — labels Démarche Numérique ↔ Grist

Gérer les labels des dossiers **Démarche Numérique** depuis un document **Grist** synchronisé par
[OTP](https://github.com/betagouv/OTP-DS-to-Grist) : widget DSFR, ajout/retrait unitaire ou en masse,
règles automatiques ET/OU, synchronisation incrémentale.

| Dossier | Contenu |
|---|---|
| `backend/` | API FastAPI + service du widget (phase 1 : socle) |
| `spikes/` | Scripts de vérification de la phase 0 et leur fiche de résultats (`RESULTATS.md`) |

## Licence et composants tiers

Code sous licence MIT (voir `LICENSE`). Le DSFR auto-hébergé dans `backend/app/static/dsfr/` est distribué
sous sa propre licence (`backend/app/static/dsfr/LICENSE.md`) ; la police Marianne est réservée aux services de l'État.

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

## Synchronisation des labels (phase 2)

| Route | Appelant | Rôle |
|---|---|---|
| `POST /api/demarches/{n}/synchro` `{"mode": "incrementale" \| "complete" \| "ciblee", "numeros": [...]}` | widget | lance en arrière-plan (202) |
| `GET /api/demarches/{n}/synchro` | widget | progression + dernier résultat (`LBL_Etat`) |
| `POST /api/taches/synchro?mode=incrementale\|complete` | n8n (`Authorization: Bearer <LBL_TASK_TOKEN>`) | synchro de toutes les démarches configurées |

- **Incrémentale** : dossiers modifiés depuis la dernière synchro réussie (marge 2 min) ; complète s'il n'y en a jamais eu.
- **Complète** : tous les dossiers (à planifier la nuit). **Ciblée** : jusqu'à 500 numéros, ne déplace pas le curseur.
- Seules les lignes dont les labels ont changé sont réécrites, au **format exact d'OTP** (`label_names`, `labels_json`).
- Tables créées automatiquement : `LBL_Catalogue` (labels de la démarche), `LBL_Etat` (une ligne par démarche).

## Widget et opérations (phases 3 et 4)

Dans Grist : **Ajouter une vue › Personnalisé**, données = `Demarche_<n>_dossiers`, URL `http://localhost:8000/widget/`,
accès **complet au document**. Onglets :

- **Dossier** : labels du dossier sélectionné, ajout / retrait immédiat dans DN, vérification DN, historique.
- **En masse** : sur les dossiers transmis au widget (filtres de sa vue, 500 max), aperçu calculé sur l'état
  réel de DN, confirmation obligatoire, ou mise en file sans envoi.
- **File et journal** : table `LBL_Operations` (une ligne par dossier et opération), envoi de la file.
- **Synchro** : incrémentale, ciblée sur les dossiers transmis, complète ; catalogue des labels.
- **Règles** : phase 5.

| Route | Rôle |
|---|---|
| `POST /api/demarches/{n}/operations/apercu` | ce que ferait l'envoi, d'après DN |
| `POST /api/demarches/{n}/operations` `{"action", "label_id", "numeros", "envoyer"}` | envoi immédiat ou mise en file |
| `POST /api/demarches/{n}/operations/file/envoyer` | envoi des opérations en attente |

Garde-fous : label vérifié dans le catalogue DN ; dossiers d'une **autre démarche** écartés (un jeton DN peut en
couvrir plusieurs) ; aucun appel DN pour un dossier déjà dans l'état voulu ; Grist mis à jour d'après la réponse de DN.

Le DSFR (CSS, police Marianne, icônes utiles) est auto-hébergé dans `app/static/dsfr/` (version dans `VERSION`).

## Règles automatiques (phase 5)

Onglet **Règles** du widget : « ajouter / retirer tel label quand… », avec des **groupes OU de conditions ET**
portant sur les colonnes OTP (dossier, champs du formulaire, annotations privées) et sur les labels.

- Opérateurs selon le type : dates (plus ancien / récent que N jours, avant / après le…), texte, nombres,
  cases à cocher, labels (a / n'a pas le label), vide / non vide.
- **Simulation** : aperçu des dossiers concernés, sans écriture. **Appliquer maintenant** : 500 dossiers au plus par passage.
- **Automatique** : exécutée par la tâche planifiée (`POST /api/taches/synchro`) après chaque synchro.
  Désactivable pour tout le serveur avec `regles_auto_autorisees: false`.
- **Verrou** (activé par défaut) : un dossier déjà traité par la règle puis modifié à la main n'est plus touché
  (mémoire dans `LBL_Regles_Traces`).
- Règles stockées dans `LBL_Regles` (conditions en JSON, revalidées par le serveur à chaque usage).
- Sécurité : champs vérifiés contre le schéma réel du document, opérateurs en liste fermée, valeurs en paramètres SQL.
- Conseil : dans Grist, **règles d'accès** sur `LBL_Regles` pour réserver la modification aux propriétaires du document.

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
