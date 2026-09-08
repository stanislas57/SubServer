from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.email_service import send_debt_reminder_email
from app.core.rate_limit import limiter
from app.core.transaction_analyzer import display_merchant_name
from app.db.session import get_db
from app.models.family_member import FamilyMember
from app.models.settlement import Settlement
from app.models.subscription import Subscription
from app.models.subscription_split import SubscriptionSplit
from app.models.user import User
from app.schemas import (
    DebtEdgeOut,
    FamilyBalanceOut,
    FamilyGroupOut,
    FamilyMemberBody,
    FamilyMemberOut,
    MessageResult,
    SendReminderBody,
    SettleDebtBody,
    SettlementOut,
    ShareableSubscriptionOut,
    SharedSubscriptionSelectionBody,
    SubscriptionSplitMemberOut,
    SubscriptionSplitOut,
    SubscriptionSplitUpdateBody,
)

router = APIRouter(prefix="/family", tags=["family"])

_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _period_label(period: str) -> str:
    """"2026-07" -> "juillet 2026" (pas de dépendance à la locale système)."""
    year, month = period.split("-")
    return f"{_FRENCH_MONTHS[int(month) - 1]} {year}"


def _today_label() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.day} {_FRENCH_MONTHS[now.month - 1]} {now.year}"

# Tolérance (même devise que les montants) sous laquelle un solde est
# considéré comme réglé -- absorbe les arrondis flottants en cascade.
_BALANCE_EPSILON = 0.01


def _current_period() -> str:
    """Mois en cours au format "YYYY-MM", auquel sont rattachés les nouveaux
    règlements (cf. Settlement.period)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ensure_owner_member(db: Session, user: User) -> None:
    """Garantit qu'un membre "owner" existe pour cet utilisateur.

    Corrige une race condition réelle : GET /family/group et GET
    /family/balances sont déclenchées quasi simultanément au montage de la
    page (deux requêtes HTTP indépendantes), et pouvaient toutes les deux
    passer ce check AVANT que l'une ou l'autre n'ait committé son insertion
    -> deux lignes "owner" créées pour le même utilisateur (bug rapporté :
    le propriétaire apparaît en double, fausse le calcul à 33%).

    L'unique véritable garde-fou est la contrainte UNIQUE en base
    (uq_family_members_one_owner_per_user, index partiel WHERE is_owner) --
    ce check applicatif reste une optimisation (évite un aller-retour DB
    inutile la plupart du temps), pas la protection elle-même. En cas de
    perdant de la course, l'IntegrityError est absorbée : l'autre requête a
    déjà créé la ligne, il n'y a rien de plus à faire.
    """
    exists = (
        db.query(FamilyMember)
        .filter(FamilyMember.user_id == user.id, FamilyMember.is_owner.is_(True))
        .first()
    )
    if exists:
        return
    try:
        db.add(FamilyMember(user_id=user.id, name=user.first_name, email=user.email, is_owner=True))
        db.commit()
    except IntegrityError:
        db.rollback()


def _get_deduplicated_members(db: Session, user_id: str) -> list[FamilyMember]:
    """Renvoie les membres du groupe, en supprimant définitivement tout
    doublon "owner" résiduel (données créées avant le correctif de la race
    condition, ou toute autre anomalie) -- déduplication basée sur l'email
    (les doublons "owner" ont le même email, celui de l'utilisateur, mais
    des id différents) et repli sur l'id si l'email est absent."""
    members = (
        db.query(FamilyMember).filter(FamilyMember.user_id == user_id).order_by(FamilyMember.id).all()
    )

    seen_keys: set[str] = set()
    deduplicated: list[FamilyMember] = []
    duplicates: list[FamilyMember] = []
    for member in members:
        key = member.email or member.id
        if key in seen_keys:
            duplicates.append(member)
            continue
        seen_keys.add(key)
        deduplicated.append(member)

    if duplicates:
        for member in duplicates:
            db.delete(member)
        db.commit()

    return deduplicated


def _compute_subscription_owed(
    subscription: Subscription, splits: list[SubscriptionSplit], all_members: list[FamilyMember]
) -> dict[str, float]:
    """Renvoie {member_id: montant dû} pour CET abonnement uniquement.

    Sans ligne SubscriptionSplit (jamais personnalisé) : partage égal entre
    TOUS les membres du groupe -- comportement historique préservé pour qui
    ne personnalise rien. Avec des lignes : seuls les membres participants
    (ceux qui ont une ligne) sont inclus, selon le split_mode de l'abonnement."""
    if not splits:
        n = len(all_members) or 1
        share = subscription.price / n
        return {m.id: share for m in all_members}

    if subscription.split_mode == "percentage":
        return {s.family_member_id: subscription.price * (s.share_value or 0) / 100 for s in splits}
    if subscription.split_mode == "fixed":
        return {s.family_member_id: (s.share_value or 0) for s in splits}

    # "equal" avec une liste de participants explicite (sous-ensemble possible du groupe)
    n = len(splits) or 1
    share = subscription.price / n
    return {s.family_member_id: share for s in splits}


def _build_split_out(db: Session, subscription: Subscription, members: list[FamilyMember]) -> SubscriptionSplitOut:
    splits = db.query(SubscriptionSplit).filter(SubscriptionSplit.subscription_id == subscription.id).all()
    owed = _compute_subscription_owed(subscription, splits, members)
    split_by_member = {s.family_member_id: s for s in splits}

    members_out = [
        SubscriptionSplitMemberOut(
            member_id=m.id,
            member_name=m.name,
            share_value=split_by_member[m.id].share_value if m.id in split_by_member else None,
            computed_amount=round(owed[m.id], 2),
        )
        for m in members
        if m.id in owed
    ]
    return SubscriptionSplitOut(
        subscription_id=subscription.id,
        display_name=display_merchant_name(subscription.name),
        price=subscription.price,
        split_mode=subscription.split_mode if splits else "equal",
        members=members_out,
    )


def _compute_all_owed(db: Session, user_id: str, members: list[FamilyMember]) -> dict[str, float]:
    """{member_id: montant dû sur l'ENSEMBLE des abonnements partagés}, tous
    membres confondus (y compris le propriétaire lui-même, qui "doit" sa
    propre part -- utilisé différemment selon l'appelant, cf.
    get_family_balances vs _compute_net_balances)."""
    shared_subscriptions = (
        db.query(Subscription).filter(Subscription.user_id == user_id, Subscription.is_shared.is_(True)).all()
    )
    # Une requête pour tous les splits plutôt qu'une par abonnement partagé
    # (N+1) -- regroupés en mémoire par subscription_id.
    sub_ids = [s.id for s in shared_subscriptions]
    splits_by_sub: dict[str, list[SubscriptionSplit]] = {}
    if sub_ids:
        all_splits = (
            db.query(SubscriptionSplit).filter(SubscriptionSplit.subscription_id.in_(sub_ids)).all()
        )
        for split in all_splits:
            splits_by_sub.setdefault(split.subscription_id, []).append(split)

    owed: dict[str, float] = {m.id: 0.0 for m in members}
    for subscription in shared_subscriptions:
        splits = splits_by_sub.get(subscription.id, [])
        for member_id, amount in _compute_subscription_owed(subscription, splits, members).items():
            if member_id in owed:  # ignore une part orpheline (membre supprimé entre-temps)
                owed[member_id] += amount
    return owed


def _compute_net_balances(db: Session, current_user: User, members: list[FamilyMember]) -> dict[str, float]:
    """Solde NET par membre pour le mois en cours : positif = doit recevoir
    (créditeur), négatif = doit payer (débiteur).

    Modèle "étoile centrée sur le propriétaire" : les abonnements partagés
    sont payés par la carte bancaire du propriétaire (c'est SON compte qui
    est connecté), donc chaque autre membre lui doit sa part calculée -- la
    propre part du propriétaire n'est due à personne (il se la paie à
    lui-même). Les règlements (Settlement) DU MOIS EN COURS réduisent
    ensuite ces soldes bruts avant simplification."""
    owed = _compute_all_owed(db, current_user.id, members)
    owner = next((m for m in members if m.is_owner), None)

    net: dict[str, float] = {}
    total_owed_to_owner = 0.0
    for member in members:
        if owner and member.id == owner.id:
            continue
        net[member.id] = -owed.get(member.id, 0.0)
        total_owed_to_owner += owed.get(member.id, 0.0)
    if owner:
        net[owner.id] = total_owed_to_owner

    period = _current_period()
    settlements = (
        db.query(Settlement)
        .filter(Settlement.user_id == current_user.id, Settlement.period == period)
        .all()
    )
    for settlement in settlements:
        if settlement.from_member_id in net:
            net[settlement.from_member_id] += settlement.amount
        if settlement.to_member_id in net:
            net[settlement.to_member_id] -= settlement.amount

    return net


def _simplify_debts(net_balances: dict[str, float]) -> list[tuple[str, str, float]]:
    """Algorithme glouton standard (min cash flow, à la Splitwise) : à chaque
    étape, le plus gros créditeur encaisse du plus gros débiteur, jusqu'à
    épuisement de l'un des deux, et ainsi de suite jusqu'à ce que tous les
    soldes soient nuls. Minimise le nombre de transactions (au plus N-1 pour
    N participants à solde non nul) -- renvoie [(from_id, to_id, amount)]."""
    balances = {member_id: amount for member_id, amount in net_balances.items() if abs(amount) > _BALANCE_EPSILON}
    transactions: list[tuple[str, str, float]] = []

    while balances:
        creditor_id = max(balances, key=lambda k: balances[k])
        debtor_id = min(balances, key=lambda k: balances[k])
        if balances[creditor_id] <= _BALANCE_EPSILON or balances[debtor_id] >= -_BALANCE_EPSILON:
            break

        amount = min(balances[creditor_id], -balances[debtor_id])
        transactions.append((debtor_id, creditor_id, round(amount, 2)))
        balances[creditor_id] -= amount
        balances[debtor_id] += amount

        if abs(balances[creditor_id]) < _BALANCE_EPSILON:
            del balances[creditor_id]
        if debtor_id in balances and abs(balances[debtor_id]) < _BALANCE_EPSILON:
            del balances[debtor_id]

    return transactions


def _get_owned_shared_subscription(db: Session, user: User, subscription_id: str) -> Subscription:
    subscription = (
        db.query(Subscription)
        .filter(Subscription.id == subscription_id, Subscription.user_id == user.id)
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Abonnement introuvable.")
    if not subscription.is_shared:
        raise HTTPException(status_code=400, detail="Cet abonnement n'est pas partagé.")
    return subscription


@router.get("/group", response_model=FamilyGroupOut)
def get_family_group(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_owner_member(db, current_user)
    members = _get_deduplicated_members(db, current_user.id)
    return FamilyGroupOut(id=current_user.id, name=f"Famille {current_user.first_name}", members=members)


@router.post("/members", response_model=FamilyMemberOut, status_code=201)
def add_family_member(
    body: FamilyMemberBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _ensure_owner_member(db, current_user)
    member = FamilyMember(user_id=current_user.id, name=body.name, email=body.email, is_owner=False)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.delete("/members/{member_id}", status_code=204)
def remove_family_member(
    member_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    # Les SubscriptionSplit référençant ce membre sont supprimés en cascade
    # par la contrainte FK (ondelete="CASCADE") -- pas de nettoyage manuel
    # nécessaire ici, cohérent avec le reste du modèle de données.
    deleted = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.id == member_id,
            FamilyMember.user_id == current_user.id,
            FamilyMember.is_owner.is_(False),
        )
        .delete()
    )
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    return None


@router.get("/shareable-subscriptions", response_model=list[ShareableSubscriptionOut])
def list_shareable_subscriptions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Abonnements de l'utilisateur avec leur statut de partage actuel, pour
    la checklist de sélection. `display_name` passe par le moteur Clé
    Marchand (jamais un libellé bancaire brut type "EDF CLIENTS
    PARTICULIERS..." avec un numéro de client), et la liste est dédupliquée
    sur cette base (ex: deux lignes "Prixtel" issues d'un import bancaire ne
    forment plus qu'une seule entrée sélectionnable)."""
    subs = (
        db.query(Subscription).filter(Subscription.user_id == current_user.id).order_by(Subscription.name).all()
    )

    seen_keys: set[str] = set()
    result: list[ShareableSubscriptionOut] = []
    for sub in subs:
        display_name = display_merchant_name(sub.name)
        key = display_name.strip().casefold()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Si un doublon caché de ce marchand est déjà partagé, on le reflète
        # ici même si CE représentant précis ne l'est pas -- évite qu'une
        # sélection existante paraisse "perdue" après dédoublonnage (la
        # première modification de sélection normalise définitivement l'état
        # sous-jacent, cf. set_shared_subscriptions).
        is_shared = any(
            other.is_shared for other in subs if display_merchant_name(other.name).strip().casefold() == key
        )
        result.append(
            ShareableSubscriptionOut(
                id=sub.id, display_name=display_name, price=sub.price, category=sub.category, is_shared=is_shared
            )
        )
    return result


@router.put("/shared-subscriptions", response_model=list[ShareableSubscriptionOut])
def set_shared_subscriptions(
    body: SharedSubscriptionSelectionBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remplace intégralement la sélection : les abonnements de
    `subscription_ids` (qui doivent appartenir à l'utilisateur -- toute id
    étrangère est silencieusement ignorée) passent à is_shared=True, tous
    les autres abonnements de l'utilisateur repassent à False."""
    selected_ids = set(body.subscription_ids)
    subscriptions = db.query(Subscription).filter(Subscription.user_id == current_user.id).all()
    for subscription in subscriptions:
        was_shared = subscription.is_shared
        subscription.is_shared = subscription.id in selected_ids
        # Un abonnement retiré du partage perd sa personnalisation de
        # répartition : la remise en partage repart d'un état neutre (égal
        # entre tous), plutôt que de faire réapparaître une vieille config.
        if was_shared and not subscription.is_shared:
            db.query(SubscriptionSplit).filter(SubscriptionSplit.subscription_id == subscription.id).delete()
    db.commit()
    return list_shareable_subscriptions(current_user, db)


@router.get("/subscriptions/{subscription_id}/split", response_model=SubscriptionSplitOut)
def get_subscription_split(
    subscription_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    subscription = _get_owned_shared_subscription(db, current_user, subscription_id)
    members = _get_deduplicated_members(db, current_user.id)
    return _build_split_out(db, subscription, members)


@router.put("/subscriptions/{subscription_id}/split", response_model=SubscriptionSplitOut)
def set_subscription_split(
    subscription_id: str,
    body: SubscriptionSplitUpdateBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Personnalise la répartition d'UN abonnement partagé : qui y participe
    (sous-ensemble possible du groupe) et selon quel mode (égal / pourcentage
    / montant fixe). Remplace intégralement la config précédente pour cet
    abonnement."""
    subscription = _get_owned_shared_subscription(db, current_user, subscription_id)
    members = _get_deduplicated_members(db, current_user.id)
    member_ids = {m.id for m in members}

    if not body.members:
        raise HTTPException(status_code=400, detail="Sélectionne au moins un membre.")

    seen_member_ids: set[str] = set()
    for entry in body.members:
        if entry.member_id not in member_ids:
            raise HTTPException(status_code=400, detail="Membre invalide.")
        if entry.member_id in seen_member_ids:
            raise HTTPException(status_code=400, detail="Un membre ne peut apparaître qu'une seule fois.")
        seen_member_ids.add(entry.member_id)

    if body.split_mode == "percentage":
        total = sum(entry.share_value or 0 for entry in body.members)
        if abs(total - 100) > 0.5:
            raise HTTPException(
                status_code=400, detail=f"Les pourcentages doivent totaliser 100% (actuellement {total:.1f}%)."
            )
    elif body.split_mode == "fixed":
        total = sum(entry.share_value or 0 for entry in body.members)
        if abs(total - subscription.price) > 0.5:
            raise HTTPException(
                status_code=400,
                detail=f"Les montants doivent totaliser le prix de l'abonnement ({subscription.price:.2f}, actuellement {total:.2f}).",
            )

    db.query(SubscriptionSplit).filter(SubscriptionSplit.subscription_id == subscription_id).delete()
    for entry in body.members:
        db.add(
            SubscriptionSplit(
                subscription_id=subscription_id,
                family_member_id=entry.member_id,
                share_value=entry.share_value if body.split_mode != "equal" else None,
            )
        )
    subscription.split_mode = body.split_mode
    db.commit()

    return _build_split_out(db, subscription, members)


@router.get("/balances", response_model=list[FamilyBalanceOut])
def get_family_balances(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Part de chacun dans le total partagé (indépendant des règlements déjà
    effectués) -- pour "qui doit réellement combien à qui", voir GET
    /family/debts, qui lui tient compte des remboursements du mois en cours."""
    _ensure_owner_member(db, current_user)
    members = _get_deduplicated_members(db, current_user.id)
    owed = _compute_all_owed(db, current_user.id, members)

    total = sum(owed.values())
    return [
        FamilyBalanceOut(
            member_id=m.id,
            member_name=m.name,
            share_percent=round(owed[m.id] / total * 100, 2) if total else 0.0,
            amount_owed=round(owed[m.id], 2),
        )
        for m in members
    ]


@router.get("/debts", response_model=list[DebtEdgeOut])
def get_family_debts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """"Qui doit combien à qui" pour le mois en cours, déjà simplifié au
    nombre minimal de transactions (règlements du mois déjà déduits)."""
    _ensure_owner_member(db, current_user)
    members = _get_deduplicated_members(db, current_user.id)
    members_by_id = {m.id: m for m in members}

    net_balances = _compute_net_balances(db, current_user, members)
    edges = _simplify_debts(net_balances)

    return [
        DebtEdgeOut(
            from_member_id=from_id,
            from_member_name=members_by_id[from_id].name,
            to_member_id=to_id,
            to_member_name=members_by_id[to_id].name,
            amount=amount,
        )
        for from_id, to_id, amount in edges
    ]


@router.post("/debts/settle", response_model=list[DebtEdgeOut])
def settle_debt(
    body: SettleDebtBody, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Enregistre un remboursement réel ("Marquer comme remboursé" sur une
    dette simplifiée) et renvoie la liste des dettes restantes, déjà mise à
    jour. Le montant n'est pas forcé à correspondre exactement à la dette
    affichée : un remboursement partiel est accepté."""
    members = _get_deduplicated_members(db, current_user.id)
    member_ids = {m.id for m in members}

    if body.from_member_id not in member_ids or body.to_member_id not in member_ids:
        raise HTTPException(status_code=400, detail="Membre invalide.")
    if body.from_member_id == body.to_member_id:
        raise HTTPException(status_code=400, detail="Un membre ne peut pas se rembourser lui-même.")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant doit être positif.")

    db.add(
        Settlement(
            user_id=current_user.id,
            from_member_id=body.from_member_id,
            to_member_id=body.to_member_id,
            amount=body.amount,
            period=_current_period(),
        )
    )
    db.commit()

    return get_family_debts(current_user, db)


@router.post("/debts/remind", response_model=MessageResult)
@limiter.limit("10/hour")
def send_debt_reminder(
    request: Request,
    body: SendReminderBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Envoie un e-mail de relance de paiement au membre débiteur -- limité en
    débit (10/heure) car chaque appel déclenche un envoi d'e-mail réel,
    identique en principe à /contact. Le créditeur est toujours l'appelant
    (modèle en étoile centré sur le propriétaire, cf. _compute_net_balances)."""
    members = _get_deduplicated_members(db, current_user.id)
    member = next((m for m in members if m.id == body.member_id), None)
    if not member:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    if member.is_owner:
        raise HTTPException(status_code=400, detail="Impossible de s'envoyer un rappel à soi-même.")
    if not member.email:
        raise HTTPException(status_code=400, detail="Ce membre n'a pas d'adresse e-mail enregistrée.")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Le montant doit être positif.")

    send_debt_reminder_email(
        to=member.email,
        member_first_name=member.name,
        owner_name=current_user.first_name,
        amount=body.amount,
        currency=current_user.currency,
        period_label=_period_label(_current_period()),
        request_date=_today_label(),
    )
    return MessageResult(message=f"Rappel envoyé à {member.name}.")


@router.get("/settlements", response_model=list[SettlementOut])
def list_settlements(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Historique des remboursements, du plus récent au plus ancien."""
    members_by_id = {m.id: m for m in _get_deduplicated_members(db, current_user.id)}
    rows = (
        db.query(Settlement)
        .filter(Settlement.user_id == current_user.id)
        .order_by(Settlement.created_at.desc())
        .all()
    )
    return [
        SettlementOut(
            id=row.id,
            from_member_id=row.from_member_id,
            from_member_name=members_by_id[row.from_member_id].name
            if row.from_member_id in members_by_id
            else "Membre supprimé",
            to_member_id=row.to_member_id,
            to_member_name=members_by_id[row.to_member_id].name
            if row.to_member_id in members_by_id
            else "Membre supprimé",
            amount=row.amount,
            period=row.period,
            created_at=row.created_at,
        )
        for row in rows
    ]
