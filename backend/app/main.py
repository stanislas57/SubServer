import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.scheduler import start_scheduler, stop_scheduler
from app.db.session import engine

# Sans ceci, un logger applicatif (logger = logging.getLogger(__name__)) reste
# muet en dessous de WARNING : le root logger n'a par défaut aucun handler
# configuré. C'est ce qui rendait un éventuel goulot d'étranglement invisible
# en production -- les logs de timing ci-dessous (et ceux de app/api/v1/auth.py)
# ne remontaient nulle part avant cet ajout.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Rien de ce qui se passe au démarrage ne doit pouvoir empêcher l'API de
    servir : une exception levée ici fait sortir uvicorn en status 1 et met
    tout le site hors ligne (le frontend n'a plus d'API du tout). On loggue
    et on continue -- /health/db reste là pour diagnostiquer."""
    try:
        start_scheduler()
    except Exception:
        logger.exception("Démarrage du scheduler en échec (API démarrée quand même).")
    yield
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Arrêt du scheduler en échec (ignoré).")


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.state.limiter = limiter


# Seuil au-delà duquel une requête est considérée comme suspecte et journalisée
# en WARNING (jamais en dessous : le bruit noierait le signal). Choisi pour
# repérer un cold start d'hébergeur (Render free tier : 30-60s après une
# période d'inactivité) ou une requête anormalement lente sans avoir besoin
# d'un APM tiers.
SLOW_REQUEST_THRESHOLD_MS = 1000


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    """Journalise la durée de CHAQUE requête -- seul moyen fiable d'isoler un
    goulot d'étranglement (login lent, cold start d'hébergeur...) sans dépendre
    d'un outil d'APM externe. INFO pour la visibilité générale, WARNING dès que
    ça dépasse SLOW_REQUEST_THRESHOLD_MS pour que ça ressorte des logs."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000

    log_line = f"{request.method} {request.url.path} -> {response.status_code} en {duration_ms:.0f}ms"
    if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
        logger.warning("[LENT] %s", log_line)
    else:
        logger.info(log_line)

    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.0f}"
    return response


@app.exception_handler(RateLimitExceeded)
def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Réponse au format {"detail": ...} -- comme toutes les erreurs FastAPI de
    l'app -- plutôt que le {"error": ...} par défaut de slowapi, pour que
    getErrorMessage() côté frontend affiche le vrai message au lieu de
    retomber sur le fallback générique."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Trop de tentatives. Réessaie dans quelques instants."},
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {"message": "Bienvenue sur SubSaver!", "status": "online"}


@app.get("/health")
def health():
    """Volontairement SANS accès base : c'est la sonde de l'hébergeur. Si elle
    dépendait de Postgres, une base momentanément injoignable ferait
    redéployer/tuer une instance par ailleurs saine. Pour tester la base,
    cf. /health/db."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Diagnostic de connexion à la base : renvoie 200 {"database": "ok"} ou
    503 avec le TYPE d'erreur SQLAlchemy (jamais le message brut, qui
    contient l'hôte et l'utilisateur de connexion)."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Health check base de données en échec.")
        return JSONResponse(status_code=503, content={"database": "unreachable", "error": type(exc).__name__})
    return {"database": "ok"}
