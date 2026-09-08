from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.renewal_alert import RenewalAlert
from app.models.user import User
from app.schemas import RenewalAlertOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(alert: RenewalAlert) -> RenewalAlertOut:
    return RenewalAlertOut(
        id=alert.id,
        subscription_id=alert.subscription_id,
        subscription_name=alert.subscription.display_name,
        price=alert.subscription.price,
        renewal_date=alert.renewal_date,
        status=alert.status,
        is_read=alert.is_read,
        created_at=alert.created_at,
    )


@router.get("", response_model=list[RenewalAlertOut])
def list_notifications(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Renvoie les alertes non traitées (status != "dismissed") de
    l'utilisateur -- c'est ce qui s'accumule dans le centre de notifications
    tant qu'elles ne sont pas lues/dismissées, les plus récentes d'abord."""
    alerts = (
        db.query(RenewalAlert)
        .options(joinedload(RenewalAlert.subscription))
        .filter(RenewalAlert.user_id == current_user.id, RenewalAlert.status != "dismissed")
        .order_by(RenewalAlert.created_at.desc())
        .all()
    )
    return [_to_out(a) for a in alerts]


def _get_owned_alert(alert_id: str, current_user: User, db: Session) -> RenewalAlert:
    alert = (
        db.query(RenewalAlert)
        .filter(RenewalAlert.id == alert_id, RenewalAlert.user_id == current_user.id)
        .first()
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Notification introuvable.")
    return alert


@router.post("/{alert_id}/read", response_model=RenewalAlertOut)
def mark_read(alert_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    alert = _get_owned_alert(alert_id, current_user, db)
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return _to_out(alert)


@router.post("/{alert_id}/dismiss", response_model=RenewalAlertOut)
def dismiss(alert_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Utilisé par la quick action "Renouveler maintenant" du frontend : il
    n'y a rien à "renouveler" côté serveur (pas d'intégration de paiement),
    l'action se contente d'acquitter l'alerte. La quick action "Supprimer"
    n'appelle PAS cette route : elle appelle DELETE /subscriptions/{id}, qui
    supprime l'alerte par cascade FK -- appeler dismiss ensuite renverrait
    un 404 puisque la ligne n'existe plus."""
    alert = _get_owned_alert(alert_id, current_user, db)
    alert.status = "dismissed"
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return _to_out(alert)
