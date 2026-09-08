import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.subscription_detector import RawTransaction
from app.core.transaction_analyzer import analyze_transactions, display_merchant_name
from app.db.session import get_db
from app.models.bank_transaction import BankTransaction
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas import CancellableSubscriptionOut, SubscriptionInput, SubscriptionOut

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("", response_model=list[SubscriptionOut])
def list_subscriptions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Subscription).filter(Subscription.user_id == current_user.id).order_by(Subscription.name).all()


@router.get("/cancellation-candidates", response_model=list[CancellableSubscriptionOut])
def list_cancellation_candidates(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Utilisé par la Lettre de résiliation : passe chaque nom d'abonnement
    dans le moteur Clé Marchand (`match_whitelist`) pour obtenir un nom propre
    ("EDF" au lieu de "EDF CLIENTS PARTICULIERS +REPRESENTATION..."), puis
    déduplique par ce nom normalisé -- les abonnements hors liste blanche
    (ajoutés manuellement) gardent simplement leur nom tel quel."""
    subs = (
        db.query(Subscription).filter(Subscription.user_id == current_user.id).order_by(Subscription.name).all()
    )
    seen_keys: set[str] = set()
    candidates: list[CancellableSubscriptionOut] = []
    for sub in subs:
        display_name = display_merchant_name(sub.name)
        key = display_name.strip().casefold()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        candidates.append(
            CancellableSubscriptionOut(id=sub.id, display_name=display_name, price=sub.price, domain=sub.domain)
        )
    return candidates


@router.post("", response_model=SubscriptionOut, status_code=201)
def create_subscription(
    body: SubscriptionInput, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    sub = Subscription(user_id=current_user.id, **body.model_dump())
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@router.put("/{sub_id}", response_model=SubscriptionOut)
def update_subscription(
    sub_id: str,
    body: SubscriptionInput,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(Subscription).filter(Subscription.id == sub_id, Subscription.user_id == current_user.id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Abonnement introuvable.")
    for field, value in body.model_dump().items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/{sub_id}", status_code=204)
def delete_subscription(
    sub_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    deleted = (
        db.query(Subscription)
        .filter(Subscription.id == sub_id, Subscription.user_id == current_user.id)
        .delete()
    )
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Abonnement introuvable.")
    return None


def _last_bank_activity_by_merchant_key(current_user: User, db: Session) -> dict[str, tuple[str, float]]:
    """Fait tourner le même moteur de détection que GET /bank/transactions/detect
    sur les transactions déjà synchronisées, pour associer à chaque marchand
    normalisé la date et le montant du dernier prélèvement bancaire repéré --
    utilisé uniquement pour enrichir l'export (jamais pour créer/modifier des
    abonnements). Vide si l'utilisateur n'a pas connecté sa banque : on
    n'affiche jamais une info bancaire non vérifiée."""
    if not current_user.bank_connected:
        return {}

    txs = db.query(BankTransaction).filter(BankTransaction.user_id == current_user.id).all()
    raw = [RawTransaction(id=t.id, wording=t.wording, value=t.value, date=t.date) for t in txs]
    try:
        analyzed = analyze_transactions(raw)
    except Exception:  # noqa: BLE001 -- enrichissement best-effort, jamais bloquant pour l'export
        return {}

    return {d.merchant.strip().casefold(): (d.last_date, d.price) for d in analyzed}


@router.get("/export")
def export_subscriptions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Un CSV exporté est par nature destiné à être partagé (colocataires,
    comptable...) : le nom exporté passe donc par le même moteur Clé Marchand
    que les autres vues partagées, jamais le libellé bancaire brut stocké en
    base (qui peut contenir un numéro de client, cf. audit confidentialité).

    Enrichi de trois colonnes calculées à partir de données déjà en base --
    jamais de champ inventé (ex : pas de statut "annulé", qui n'existe pas
    dans le modèle Subscription) :
    - cout_annuel : price * 12 (seule fréquence supportée par Subscription,
      cf. billing_day qui est un jour du mois)
    - statut : "En essai" tant que trial_end_date n'est pas dépassée, sinon "Actif"
    - dernier_prelevement_detecte / montant_detecte : dernier prélèvement
      bancaire retrouvé par le moteur de détection pour ce marchand (vide si
      banque non connectée ou aucune correspondance)."""
    rows = db.query(Subscription).filter(Subscription.user_id == current_user.id).order_by(Subscription.name).all()
    bank_activity = _last_bank_activity_by_merchant_key(current_user, db)
    today = date.today()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "name", "price", "category", "domain", "billing_day", "importance", "start_date", "trial_end_date",
            "cout_annuel", "partage", "statut", "dernier_prelevement_detecte", "montant_detecte",
        ]
    )
    for r in rows:
        display_name = display_merchant_name(r.name)
        en_essai = bool(r.trial_end_date) and date.fromisoformat(r.trial_end_date[:10]) >= today
        last_date, last_amount = bank_activity.get(display_name.strip().casefold(), ("", ""))
        writer.writerow(
            [
                display_name, r.price, r.category, r.domain, r.billing_day, r.importance, r.start_date, r.trial_end_date,
                round(r.price * 12, 2), "Oui" if r.is_shared else "Non", "En essai" if en_essai else "Actif",
                last_date, last_amount,
            ]
        )
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=subsaver-abonnements.csv"},
    )
