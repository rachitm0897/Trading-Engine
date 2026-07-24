from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit.models import OutboxEvent
from apps.reconciliation.models import ReconciliationBreak

from .models import CapitalReservation, KillSwitch, PreTradeRiskPolicy, RiskCheckResult


ACTIVE_ORDER_STATUSES = {
    "CREATED", "RISK_APPROVED", "QUEUED", "SUBMITTED", "ACKNOWLEDGED",
    "PARTIALLY_FILLED", "CANCEL_PENDING", "UNKNOWN",
}
RESERVED_SELL_INTENT_STATUSES = {
    "PENDING", "CLAIMED", "RISK_APPROVED", "SUBMITTING", "QUEUED", "BROKER_BLOCKED",
}


def order_quantity_error(portfolio, instrument, quantity):
    quantity = Decimal(quantity)
    minimum = Decimal(portfolio.minimum_quantity)
    if quantity < minimum:
        return f"quantity must be at least the portfolio minimum of {minimum}"
    lot_size = Decimal(instrument.lot_size or 1)
    if lot_size <= 0:
        return "Instrument lot_size must be positive"
    if not instrument.fractional_support and quantity % lot_size != 0:
        return (
            f"quantity must be a whole multiple of lot_size {lot_size} "
            "because fractional trading is disabled"
        )
    return ""


def _reserved_sell_quantity(intent):
    from apps.oms.models import OrderIntent

    candidates = (
        OrderIntent.objects.filter(
            portfolio=intent.portfolio,
            instrument=intent.instrument,
            side="SELL",
        )
        .exclude(pk=intent.pk)
        .select_related("order")
    )
    reserved = Decimal(0)
    for candidate in candidates:
        if hasattr(candidate, "order"):
            if candidate.order.status in ACTIVE_ORDER_STATUSES:
                reserved += max(
                    Decimal(candidate.order.quantity)
                    - Decimal(candidate.order.filled_quantity),
                    Decimal(0),
                )
            continue
        if candidate.operation_status in RESERVED_SELL_INTENT_STATUSES:
            reserved += Decimal(candidate.quantity)
    return reserved


def _matching_kill_switches(intent):
    account = intent.portfolio.account
    account_ids = [str(account.pk), account.account_id]
    strategy_ids = []
    if intent.strategy_instance_id:
        strategy_ids.append(str(intent.strategy_instance_id))
    query = Q(scope__iexact="GLOBAL", scope_id__in=["", "*"])
    query |= Q(scope__iexact="ACCOUNT", scope_id__in=account_ids)
    query |= Q(scope__iexact="PORTFOLIO", scope_id=str(intent.portfolio_id))
    query |= Q(scope__iexact="INSTRUMENT", scope_id=str(intent.instrument_id))
    if strategy_ids:
        query |= Q(scope__iexact="STRATEGY", scope_id__in=strategy_ids)
        query |= Q(scope__iexact="STRATEGY_INSTANCE", scope_id__in=strategy_ids)
    return KillSwitch.objects.filter(query, enabled=True)


def _unreserved_committed_capital(intent, policy):
    from apps.oms.models import OrderIntent

    reserved_intent_ids = CapitalReservation.objects.filter(
        account=intent.portfolio.account,
        status__in=["ACTIVE", "CONSUMED"],
        order_intent__isnull=False,
    ).values("order_intent_id")
    candidates = OrderIntent.objects.filter(
        portfolio__account=intent.portfolio.account,
        side="BUY",
    ).exclude(pk=intent.pk).exclude(pk__in=reserved_intent_ids).filter(
        Q(operation_status__in=["RISK_APPROVED", "SUBMITTING", "QUEUED"])
        | Q(order__status__in=ACTIVE_ORDER_STATUSES)
    )
    committed = Decimal(0)
    for candidate in candidates:
        price = Decimal(candidate.reference_price or candidate.limit_price or 0)
        if price <= 0:
            continue
        notional = Decimal(candidate.quantity) * price
        committed += notional + notional * Decimal(policy.estimated_commission_rate) + Decimal(policy.estimated_fixed_fee)
    return committed


@transaction.atomic
def evaluate_intent(intent, gateway_state=None):
    from apps.accounts.models import BrokerAccount
    from apps.oms.models import OrderIntent

    gateway_state = gateway_state or {}
    intent = OrderIntent.objects.select_for_update(of=("self",)).select_related(
        "portfolio__account", "instrument", "strategy_instance"
    ).get(pk=intent.pk)
    account = BrokerAccount.objects.select_for_update().get(pk=intent.portfolio.account_id)
    intent.portfolio.account = account
    policy, _ = PreTradeRiskPolicy.objects.get_or_create(portfolio=intent.portfolio)
    policy = PreTradeRiskPolicy.objects.select_for_update().get(pk=policy.pk)
    requested = Decimal(intent.quantity)
    approved = requested
    checks = []

    def add(name, decision, reason, qty=None, details=None):
        nonlocal approved
        if qty is not None:
            approved = min(approved, Decimal(qty))
        check = RiskCheckResult.objects.create(
            order_intent=intent,
            check_name=name,
            decision=decision,
            reason=reason,
            requested_quantity=requested,
            approved_quantity=approved,
            details=details or {},
        )
        checks.append(check)
        OutboxEvent.objects.create(
            topic="risk.decisions.v1",
            event_type="risk.decision.recorded",
            aggregate_type="order_intent",
            aggregate_id=str(intent.pk),
            partition_key=intent.idempotency_key,
            payload={
                "risk_check_id":check.pk,"check":name,"decision":decision,
                "requested_quantity":str(requested),"approved_quantity":str(approved),
                "reason":reason,"origin":intent.origin,
            },
            idempotency_key=f"risk-check:{check.pk}:recorded",
        )

    model_killed = (
        settings.GLOBAL_KILL_SWITCH
        or intent.portfolio.kill_switch
        or account.kill_switch
        or bool(intent.strategy_instance_id and intent.strategy_instance.kill_switch)
    )
    matched_switches = list(_matching_kill_switches(intent).values("scope", "scope_id", "reason"))
    if model_killed or matched_switches:
        add("kill_switch", "REJECTED", "A matching kill switch is active", 0, {"matches": matched_switches})
        return "REJECTED", Decimal(0), checks
    if not policy.enabled:
        add("risk_policy", "REJECTED", "Pre-trade risk policy is disabled", 0)
        return "REJECTED", Decimal(0), checks
    if not gateway_state.get("connected", False):
        add("gateway", "HELD", "Gateway is disconnected", 0)
        return "HELD", Decimal(0), checks
    broker_mode=str(gateway_state.get("mode", "")).lower()
    if broker_mode not in {"paper","live"}:
        add("gateway_mode", "REJECTED", "Gateway must report paper or live mode", 0)
        return "REJECTED", Decimal(0), checks
    if broker_mode=="live" and not settings.ALLOW_LIVE_TRADING:
        add("live_trading", "REJECTED", "Live order routing is disabled by deployment policy", 0)
        return "REJECTED", Decimal(0), checks
    account_breaks = ReconciliationBreak.objects.filter(
        run__broker_account=account, material=True, resolved=False
    ).exists()
    if not gateway_state.get("reconciled", False) or account_breaks:
        add("reconciliation", "HELD", "Broker account state is not reconciled", 0)
        return "HELD", Decimal(0), checks
    if not intent.instrument.tradable:
        add("instrument", "REJECTED", "Instrument is not tradable", 0)
        return "REJECTED", Decimal(0), checks
    if not intent.eligible:
        add("execution_sequence", "HELD", "Intent is waiting for sell-stage completion", 0)
        return "HELD", Decimal(0), checks
    quantity_error = order_quantity_error(intent.portfolio, intent.instrument, requested)
    if quantity_error:
        add("order_quantity", "REJECTED", quantity_error, 0)
        return "REJECTED", Decimal(0), checks

    from apps.risk.pricing import (
        OrderPriceUnavailable,
        resolve_order_risk_price,
        trusted_market_price,
    )

    try:
        if intent.requires_fresh_price:
            trusted_market_price(intent.instrument)
        if intent.origin == OrderIntent.Origin.MANUAL or intent.requires_fresh_price:
            price = resolve_order_risk_price(
                intent.instrument,
                intent.order_type,
                intent.side,
                limit_price=intent.limit_price,
                stop_price=intent.stop_price,
            )
            if intent.reference_price != price:
                intent.reference_price = price
                intent.save(update_fields=["reference_price"])
        else:
            price = Decimal(intent.reference_price or intent.limit_price or 0)
    except OrderPriceUnavailable as exc:
        add("market_freshness", "REJECTED", str(exc), 0)
        return "REJECTED", Decimal(0), checks

    if hasattr(intent, "sizing_decision"):
        sized = Decimal(intent.sizing_decision.approved_quantity)
        if sized <= 0:
            add("position_sizing", "REJECTED", intent.sizing_decision.rejected_reason or "Position sizing approved zero quantity", 0)
            return "REJECTED", Decimal(0), checks
        approved = min(approved, sized)

    approved = min(approved, Decimal(policy.maximum_order_quantity))
    if price > 0:
        approved = min(approved, Decimal(policy.maximum_order_notional) / price)
    if approved <= 0:
        add("policy_limits", "REJECTED", "Persisted risk policy approved zero quantity", 0)
        return "REJECTED", Decimal(0), checks

    decision = "RESIZED" if approved < requested else "APPROVED"
    if intent.side == "SELL":
        from apps.portfolios.models import PortfolioPosition

        position = (
            PortfolioPosition.objects.select_for_update()
            .filter(portfolio=intent.portfolio, instrument=intent.instrument)
            .first()
        )
        long_position = max(
            Decimal(position.quantity) if position is not None else Decimal(0),
            Decimal(0),
        )
        reserved_sell = _reserved_sell_quantity(intent)
        available_position = max(long_position - reserved_sell, Decimal(0))
        if requested > available_position:
            add(
                "available_position",
                "REJECTED",
                "SELL quantity exceeds the available unreserved long position; short selling is disabled",
                0,
                {
                    "long_position": str(long_position),
                    "reserved_sell_quantity": str(reserved_sell),
                    "available_position_quantity": str(available_position),
                    "short_selling_enabled": False,
                },
            )
            return "REJECTED", Decimal(0), checks

    if intent.side == "BUY" and price > 0:
        notional = approved * price
        fees = notional * Decimal(policy.estimated_commission_rate) + Decimal(policy.estimated_fixed_fee)
        already_reserved = CapitalReservation.objects.filter(
            account=account, status__in=["ACTIVE", "CONSUMED"]
        ).exclude(order_intent=intent).aggregate(models_sum=Sum("amount"))["models_sum"] or Decimal(0)
        committed_without_reservation = _unreserved_committed_capital(intent, policy)
        available = Decimal(account.available_cash) * (Decimal(1) - Decimal(intent.portfolio.cash_buffer_pct))
        required = notional + fees
        if required + Decimal(already_reserved) + committed_without_reservation > available:
            add("available_cash", "HELD", "Order exceeds cash after active reservations, fees, and pending withdrawals", 0,
                {"available":str(available),"reserved":str(already_reserved),
                 "unreserved_commitments":str(committed_without_reservation),"required":str(required)})
            return "HELD", Decimal(0), checks
        CapitalReservation.objects.update_or_create(
            idempotency_key=f"capital:order-intent:{intent.pk}",
            defaults={
                "account":account,"portfolio":intent.portfolio,"order_intent":intent,
                "reference_type":"ORDER_INTENT","reference_id":str(intent.pk),"amount":required,
                "estimated_fees":fees,"status":"ACTIVE","released_at":None,
            },
        )

    intent.operation_status = "RISK_APPROVED"
    intent.save(update_fields=["operation_status"])
    add("pre_trade", decision, "Persisted policy and capital checks passed", approved,
        {"policy_id":policy.pk,"policy_version":policy.version})
    return decision, approved, checks


@transaction.atomic
def settle_order_reservation(order, terminal_status):
    reservation = CapitalReservation.objects.select_for_update().filter(order_intent=order.intent).first()
    if not reservation:
        return None
    if terminal_status == "FILLED":
        reservation.status = "CONSUMED"
        reservation.released_at = None
    elif terminal_status in {"CANCELLED", "REJECTED", "EXPIRED"}:
        reservation.status = "RELEASED"
        reservation.released_at = timezone.now()
    else:
        return reservation
    reservation.save(update_fields=["status", "released_at"])
    return reservation
