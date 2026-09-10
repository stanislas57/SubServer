"""Scheduler in-process (APScheduler) pour le job quotidien de génération des
alertes de renouvellement. Pas de Celery/Redis dans ce projet -- pour un
unique job léger tournant une fois par jour, un scheduler en mémoire suffit
et évite d'ajouter de l'infra. Limite connue : sur un déploiement multi-
instance, chaque instance lancerait le job -- sans conséquence ici grâce à la
déduplication par contrainte unique (cf. app/core/renewal_alerts.py), mais à
remplacer par un vrai scheduler partagé (Celery beat, cron système appelant
un endpoint dédié...) si l'app passe un jour en multi-instance.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.renewal_alerts import generate_and_send_renewal_alerts
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Europe/Paris")


def _run_renewal_alerts_job() -> None:
    db = SessionLocal()
    try:
        count = generate_and_send_renewal_alerts(db)
        logger.info("Job alertes de renouvellement : %d alerte(s) créée(s).", count)
    except Exception:
        # Une base injoignable ou une migration en retard ne doit pas
        # désarmer le job : APScheduler le relancera au prochain cycle.
        logger.exception("Job alertes de renouvellement en échec.")
    finally:
        db.close()


def start_scheduler() -> None:
    """Ne propage JAMAIS d'exception : le scheduler est une commodité (un
    email de rappel), l'API est le service. Une exception ici remonterait
    dans le hook de démarrage FastAPI et tuerait le process au boot -- ce qui
    ne se voit que comme un "Exited with status 1" chez l'hébergeur, avec
    tout le site hors ligne pour une fonctionnalité annexe."""
    if scheduler.running:
        return
    try:
        # 08:00 Europe/Paris : après l'heure de nuit, avant que l'utilisateur ne
        # commence sa journée -- cohérent avec l'heure d'envoi des autres emails
        # transactionnels de l'app (aucune contrainte technique particulière).
        scheduler.add_job(
            _run_renewal_alerts_job,
            "cron",
            hour=8,
            minute=0,
            id="renewal_alerts_daily",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        scheduler.start()
    except Exception:
        logger.exception("Scheduler non démarré : les alertes de renouvellement ne seront pas envoyées.")


def stop_scheduler() -> None:
    try:
        if scheduler.running:
            scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("Arrêt du scheduler en échec (ignoré).")
