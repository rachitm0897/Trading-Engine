from decimal import Decimal
from django.conf import settings
from django.db import transaction
from apps.reconciliation.models import ReconciliationBreak
from .models import KillSwitch, RiskCheckResult

@transaction.atomic
def evaluate_intent(intent, limits=None, gateway_state=None):
    limits = limits or {}; gateway_state = gateway_state or {}
    requested = Decimal(intent.quantity); approved = requested
    checks = []
    def add(name, decision, reason, qty=None):
        nonlocal approved
        if qty is not None: approved = min(approved, Decimal(qty))
        checks.append(RiskCheckResult.objects.create(order_intent=intent, check_name=name, decision=decision, reason=reason, requested_quantity=requested, approved_quantity=approved, details={}))
    killed = settings.GLOBAL_KILL_SWITCH or intent.portfolio.kill_switch or intent.portfolio.account.kill_switch or (intent.strategy and intent.strategy.kill_switch) or KillSwitch.objects.filter(enabled=True).exists()
    if killed: add("kill_switch", "REJECTED", "A kill switch is active", 0); return "REJECTED", Decimal(0), checks
    if not gateway_state.get("connected", False): add("gateway", "HELD", "Gateway is disconnected", 0); return "HELD", Decimal(0), checks
    if str(gateway_state.get("mode","paper")).lower() == "live" and not settings.ALLOW_LIVE_TRADING: add("live_trading", "REJECTED", "Backend live trading permission is disabled", 0); return "REJECTED", Decimal(0), checks
    if not gateway_state.get("reconciled", False) or ReconciliationBreak.objects.filter(material=True, resolved=False).exists(): add("reconciliation", "HELD", "Broker state is not reconciled", 0); return "HELD", Decimal(0), checks
    if not intent.instrument.tradable: add("instrument", "REJECTED", "Instrument is not tradable", 0); return "REJECTED", Decimal(0), checks
    max_qty = Decimal(str(limits.get("max_quantity", requested)))
    if requested > max_qty: add("max_quantity", "RESIZED", "Quantity reduced to configured maximum", max_qty); return "RESIZED", approved, checks
    price = Decimal(intent.reference_price or intent.limit_price or 0)
    max_notional = Decimal(str(limits.get("max_notional", "100000")))
    if price > 0 and requested * price > max_notional:
        resized = max_notional / price
        add("max_notional", "RESIZED", "Quantity reduced to configured notional maximum", resized); return "RESIZED", approved, checks
    if intent.side == "BUY" and price > 0:
        available = Decimal(intent.portfolio.account.available_cash) * (Decimal(1) - Decimal(intent.portfolio.cash_buffer_pct))
        if requested * price > available: add("available_cash", "HELD", "Order exceeds cash available after reserve", 0); return "HELD", Decimal(0), checks
    add("pre_trade", "APPROVED", "All configured checks passed")
    return "APPROVED", approved, checks
