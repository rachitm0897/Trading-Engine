import hashlib, json
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .engine import calculate
from .models import HistoricalBar, StrategyRun, StrategyTarget

@transaction.atomic
def run_strategy(strategy):
    if not strategy.enabled or strategy.kill_switch: raise ValueError("Strategy is paused or killed")
    series = {}
    instruments = list(strategy.universe.order_by("symbol"))
    for instrument in instruments:
        series[instrument.symbol] = list(HistoricalBar.objects.filter(instrument=instrument).order_by("timestamp").values("open", "high", "low", "close", "volume"))
    snapshot = {"type": strategy.strategy_type, "version": strategy.version, "configuration": strategy.configuration, "series": series}
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    run, created = StrategyRun.objects.get_or_create(strategy=strategy, input_hash=digest, defaults={"configuration_snapshot": strategy.configuration})
    if not created: return run
    targets = calculate(strategy.strategy_type, strategy.configuration, series)
    by_symbol = {x.symbol: x for x in instruments}
    cap = Decimal(strategy.maximum_target_weight)
    StrategyTarget.objects.bulk_create([StrategyTarget(run=run, instrument=by_symbol[s], target_weight=max(-cap, min(cap, w)), rationale=strategy.strategy_type) for s, w in targets.items() if s in by_symbol])
    run.status = "COMPLETED"; run.completed_at = timezone.now(); run.save(update_fields=["status", "completed_at"])
    return run

