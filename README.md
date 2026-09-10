# SubSaver

Gestionnaire d'abonnements : abonnement partagé, comparateur d'offres (base curatée), connexion bancaire réelle (Powens sandbox) avec détection automatique des abonnements.

- **Frontend** : React 19 + Vite + TypeScript + Tailwind + React Query + Framer Motion - `frontend/`
- **Backend** : FastAPI + SQLAlchemy + Alembic + PostgreSQL - `backend/`

**Déployé** : https://subsaver.fr (API : https://subserver-urna.onrender.com)

---

## Prérequis

- Node.js ≥ 20
- Python ≥ 3.11
- PostgreSQL ≥ 14 (local ou Docker)

---

## 1. Base de données

```bash
docker run --name subsaver-db -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=subsaver -p 5432:5432 -d postgres:16

# Ou install locale (Ubuntu/Debian) :
sudo service postgresql start
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'postgres';"
sudo -u postgres psql -c "CREATE DATABASE subsaver;"
```

---

## 2. Backend (FastAPI)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Édite .env : DATABASE_URL, SECRET_KEY, CORS_ORIGINS, et les 4 variables POWENS_* (voir ci-dessous)

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API sur `http://localhost:8000`, doc interactive sur `http://localhost:8000/docs`.

**Variables d'environnement** (`backend/.env.example`) :

| Variable | Description |
|---|---|
| `DATABASE_URL` | URL de connexion PostgreSQL |
| `SECRET_KEY` | Clé de signature JWT - **à changer en production** |
| `ALGORITHM` | Algorithme JWT (`HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée de validité du token (`10080` = 7 jours) |
| `CORS_ORIGINS` | Origines autorisées (JSON list) |
| `POWENS_DOMAIN` | Domaine sandbox/prod Powens (ex: `xxx-sandbox.biapi.pro`) |
| `POWENS_CLIENT_ID` | Identifiant client Powens - **ne jamais committer** |
| `POWENS_CLIENT_SECRET` | Secret client Powens - **ne jamais committer** |
| `POWENS_REDIRECT_URI` | URL de retour après la Webview Powens (ex: `.../subscriptions`) |

### Tests

```bash
cd backend && source .venv/bin/activate
pytest tests/ -v
```

12 tests e2e (`tests/test_bank_flow.py`) : connect-url réel (sandbox Powens), sécurité du callback, sync transactions, algorithme de détection, création d'abonnement.

---

## 3. Frontend (Vite + React)

```bash
cd frontend
npm install
cp .env.example .env

npm run dev      # http://localhost:5173
npm run build    # -> dist/
npm run preview
```

**Variables d'environnement** (`frontend/.env.example`) :

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | URL de base de l'API backend |
| `VITE_STRIPE_BILLING_URL` | Lien du portail de facturation Stripe |

---

## 4. Lancer l'ensemble en local

```bash
# Terminal 1
sudo service postgresql start

# Terminal 2
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --port 8000

# Terminal 3
cd frontend && npm run dev
```

Ouvre `http://localhost:5173`, crée un compte via `/register`.

---

## Fonctionnalités

- **Abonnements** : CRUD, calendrier, analytique, export CSV
- **Connexion bancaire réelle** (Powens, Bank API de base, flow Webview redirect) : `/subscriptions` → "Connecter ma banque" → détection automatique des abonnements récurrents (algorithme maison : nettoyage libellés + matching récurrence 7/30/365 jours)
- **Abonnement partagé** : groupe, membres, répartition des coûts (accessible depuis Premium)
- **Comparateur d'offres** : base curatée d'offres réelles (Streaming, Musique, Téléphonie), mise à jour manuelle - accessible depuis Premium (premium requis)
- **Lettre de résiliation** : génération 100% client-side, accessible depuis Premium
- **Refonte visuelle** : tilt 3D + micro-interactions (Framer Motion + CSS 3D transforms)

---

## Structure du projet

```
frontend/
└── src/
    ├── api/                axiosClient.ts, config.ts
    ├── services/           auth, user, subscription, bank, market, sharedSubscription
    ├── hooks/              useSubscriptions, useBank, useProfile, useMarket, useSharedSubscription
    ├── lib/                format.ts, utils.ts, motion.ts, cancellationLetter.ts
    ├── pages/              Dashboard, Subscriptions, SubscriptionAdd, Analytics, Calendar,
    │                       Premium (inclut comparateur/résiliation/abonnement partagé),
    │                       LabComparatorPage, LabCancellationPage, Profile, Login, Register
    └── components/
        ├── ui/             button, card, tilt-card, dialog, input, select, tabs…
        ├── shared/         StatCard, FeatureBox, PremiumLockModal, EmptyState…
        ├── subscriptions/  SubscriptionForm, SubscriptionList, SubscriptionListItem
        ├── bank/           BankGrid, DetectedSubscriptionsDialog
        ├── shared-subscription/  SharedSubscriptionTabs/Modal/MemberRow/BalanceCard
        ├── lab/            ComparatorOfferCard
        └── layout/         Sidebar (nav animée), Topbar, NavLink

backend/
├── requirements.txt
├── alembic/versions/       migrations (schema initial, powens, bank_transactions, market_offers)
├── tests/                  test_bank_flow.py (12 tests e2e)
└── app/
    ├── main.py
    ├── schemas.py
    ├── core/               config.py, security.py, powens.py (client Powens), subscription_detector.py (algo)
    ├── models/             user, subscription, family_member, bank_transaction, market_offer
    └── api/v1/             auth, users, subscriptions, bank, market, family
```

---

## Déploiement (Render)

| Service | Root Directory | Build Command | Start / Publish |
|---|---|---|---|
| Frontend (Static Site) | `frontend` | `npm install && npm run build` | Publish directory : `dist` |
| Backend (Web Service) | `backend` | `pip install -r requirements.txt` | Start Command : `./start.sh` |

`backend/start.sh` applique les migrations Alembic (`alembic upgrade head`),
lance un diagnostic `scripts/verify_db.py`, puis démarre uvicorn sur
`0.0.0.0:$PORT`. Un échec de migration n'empêche PAS l'API de démarrer :
mieux vaut une API qui répond et qu'on peut diagnostiquer qu'une boucle de
crash qui met tout le site hors ligne.

> **Les migrations tournent dans le Start Command, jamais dans le Build
> Command.** Un `alembic upgrade head` placé dans le Build fait échouer tout
> le déploiement (`==> Build failed`) au moindre souci de base -- exactement
> le symptôme d'une base expirée. Build Command = `pip install -r requirements.txt`
> et rien d'autre.

**Health checks** :

| Route | Rôle |
|---|---|
| `GET /health` | Sonde de l'hébergeur. Ne touche pas la base (sinon une base momentanément injoignable ferait tuer une instance saine). |
| `GET /health/db` | Diagnostic : `200 {"database":"ok"}` ou `503 {"database":"unreachable"}`. |

**Variables d'environnement obligatoires côté backend Render** :
`ENVIRONMENT=production`, `DATABASE_URL`, `SECRET_KEY` (32 caractères minimum),
`CORS_ORIGINS` (liste JSON contenant l'origine réelle du frontend, ex.
`["https://subsaver.fr","https://www.subsaver.fr"]`).

`DATABASE_URL` se colle **telle quelle** depuis le dashboard du fournisseur.
`app/db/session.py` la normalise au démarrage : `postgres://` /
`postgresql://` -> `postgresql+psycopg2://`, et `sslmode=require` ajouté si
l'hôte l'impose (Neon, Supabase, Render).

### Base de données : Neon (gratuit, permanent)

Le Postgres gratuit de Render est **supprimé 30 jours après sa création**.
Pour une base gratuite qui ne disparaît pas, utiliser [Neon](https://neon.com) :

1. Neon -> **New Project** -> région **Europe (Frankfurt)** (au plus près du
   backend Render).
2. **Connection Details** -> copier la connection string **"direct"** (celle
   *sans* `-pooler` dans l'hôte).
3. Render -> service backend -> **Environment** -> `DATABASE_URL` = cette
   string -> **Save Changes**.
4. Render -> **Manual Deploy -> Deploy latest commit**. `start.sh` crée tout
   le schéma (`alembic upgrade head`) et peuple le catalogue d'offres via les
   migrations de données.
5. Vérifier : `curl .../health/db` -> `{"database":"ok"}`.

La base Neon se met en veille après ~5 min d'inactivité et se réveille seule
au premier appel (première requête un peu lente, `pool_pre_ping` gère la
reconnexion).

### Si l'API est hors ligne

1. Render -> service backend -> onglet **Events**, ouvrir le dernier deploy :
   la dernière traceback avant `==> Build failed` / `Exited with status 1`
   nomme la cause.
2. `could not translate host name "dpg-..."` / `Name or service not known` ->
   la base **n'existe plus** (Render free supprimée après 30 j). Recréer la
   base (Neon recommandé, cf. ci-dessus), mettre à jour `DATABASE_URL`.
3. `curl https://subserver-urna.onrender.com/health` -> l'API démarre-t-elle ?
4. `curl https://subserver-urna.onrender.com/health/db` -> la base répond-elle ?

---

## Notes

- `bank/providers` reste un catalogue de démonstration ; la vraie connexion passe par `bank/connect-url` + `bank/callback` (Powens).
- `market/offers` est une base curatée manuellement (pas de scraping/API tierce) - mise à jour via nouvelle migration Alembic en cas de changement tarifaire.
- Toute évolution de modèle : `alembic revision --autogenerate -m "message"` puis `alembic upgrade head`.
- JWT stocké côté frontend dans `localStorage` (clé `subsaver_token`).
- Base Postgres Render (plan free) : vérifier la date d'expiration et upgrader si besoin.
