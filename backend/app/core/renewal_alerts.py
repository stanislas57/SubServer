"""Génération des alertes de renouvellement -- job quotidien (cf.
app/core/scheduler.py) qui parcourt tous les abonnements et crée + envoie une
`RenewalAlert` pour chaque cycle qui entre dans la fenêtre de préavis choisie
par l'utilisateur (`User.alert_delay_days`).

Déduplication : avant de créer une ligne, on vérifie qu'aucune
`RenewalAlert(subscription_id, renewal_date)` n'existe déjà (la contrainte
unique en base est le filet de sécurité final en cas de double exécution
concurrente). Comme le job tourne chaque jour et la fenêtre couvre
[0, alert_delay_days], un jour de job manqué (panne, redeploy) est rattrapé
le lendemain sans jamais produire de second email pour le même cycle.
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session, selectinload

from app.core.email_service import send_renewal_alert_email
from app.core.renewal import next_renewal_date
from app.models.renewal_alert import RenewalAlert
from app.models.user import User

logger = logging.getLogger(__name__)


def generate_and_send_renewal_alerts(db: Session, *, today: date | None = None) -> int:
    today = today or date.today()
    sent_count = 0

    # notification_pref == "none" coupe déjà toutes les alertes existantes
    # (essais, doublons) côté client -- les alertes de renouvellement
    # respectent la même coupure globale plutôt que d'ajouter un second
    # interrupteur que l'utilisateur devrait découvrir séparément.
    # selectinload évite un aller-retour DB par utilisateur pour
    # user.subscriptions (lazy par défaut) -- 1 requête pour tous les users +
    # 1 pour toutes leurs subscriptions plutôt que N.
    users = (
        db.query(User)
        .filter(User.notification_pref != "none")
        .options(selectinload(User.subscriptions))
        .all()
    )

    # Alertes déjà créées, chargées une seule fois pour toutes les
    # subscriptions du batch plutôt qu'une requête de dédup par subscription
    # (N+1) -- chaque (subscription_id, renewal_date) n'est de toute façon
    # généré qu'une fois par exécution, donc ce snapshot pris avant la boucle
    # reste valide pendant toute la durée du job.
    all_sub_ids = [sub.id for user in users for sub in user.subscriptions]
    existing_alerts = (
        {
            (a.subscription_id, a.renewal_date)
            for a in db.query(RenewalAlert.subscription_id, RenewalAlert.renewal_date).filter(
                RenewalAlert.subscription_id.in_(all_sub_ids)
            )
        }
        if all_sub_ids
        else set()
    )

    for user in users:
        for sub in user.subscriptions:
            renewal_date = next_renewal_date(sub.billing_day, today)
            days_before = (renewal_date - today).days
            if days_before < 0 or days_before > user.alert_delay_days:
                continue

            renewal_date_iso = renewal_date.isoformat()
            if (sub.id, renewal_date_iso) in existing_alerts:
                continue

            alert = RenewalAlert(
                user_id=user.id,
                subscription_id=sub.id,
                renewal_date=renewal_date_iso,
                status="pending",
            )
            db.add(alert)
            try:
                db.flush()
            except Exception:
                # Course concurrente sur la contrainte unique (deux exécutions
                # du job en parallèle) : un autre process a déjà créé la ligne
                # pour ce cycle, on abandonne celle-ci sans planter le job.
                db.rollback()
                logger.info("Alerte déjà créée pour subscription=%s cycle=%s (course évitée).", sub.id, renewal_date_iso)
                continue

            try:
                send_renewal_alert_email(
                    to=user.email,
                    first_name=user.first_name,
                    subscription_name=sub.display_name,
                    price=sub.price,
                    currency=user.currency,
                    renewal_date_label=renewal_date.strftime("%d/%m/%Y"),
                    days_before=days_before,
                )
                alert.status = "sent"
                alert.sent_at = datetime.now(timezone.utc).isoformat()
            except Exception:
                logger.exception("Échec d'envoi de l'email de renouvellement pour subscription=%s.", sub.id)
                # L'alerte reste visible in-app (status="pending") même si
                # l'email a échoué -- mieux vaut prévenir dans l'app que ne
                # rien montrer du tout à cause d'un souci SMTP transitoire.

            db.commit()
            sent_count += 1

    return sent_count
