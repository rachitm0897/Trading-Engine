from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.instruments.models import Instrument
from apps.portfolio_optimization.models import PortfolioUniverseInstrument

from .models import InstrumentPriceHistory
from .services import fetch_daily_history


@shared_task
def sync_finnhub_history(instrument_id, days=400, purpose="INCREMENTAL"):
    instrument = Instrument.objects.get(pk=instrument_id)
    end_date = timezone.now().date()
    latest = InstrumentPriceHistory.objects.filter(instrument=instrument, provider="FINNHUB").order_by("-trading_date").first()
    start_date = latest.trading_date + timedelta(days=1) if latest else end_date - timedelta(days=int(days))
    if start_date > end_date:
        return {"instrument_id": instrument_id, "status": "CURRENT"}
    run = fetch_daily_history(instrument, start_date, end_date, purpose=purpose)
    return {"instrument_id": instrument_id, "fetch_run_id": run.pk, "records": run.records_received}


@shared_task
def sync_active_finnhub_universes():
    instrument_ids = PortfolioUniverseInstrument.objects.filter(
        enabled=True, universe__enabled=True
    ).values_list("instrument_id", flat=True).distinct()
    queued = 0
    for instrument_id in instrument_ids:
        sync_finnhub_history.delay(instrument_id)
        queued += 1
    return queued


@shared_task
def repair_finnhub_history(instrument_id, start_date, end_date):
    instrument = Instrument.objects.get(pk=instrument_id)
    run = fetch_daily_history(instrument, start_date, end_date, purpose="REPAIR")
    return {"fetch_run_id": run.pk, "records": run.records_received}


@shared_task
def check_finnhub_history_staleness(max_age_days=3):
    cutoff = timezone.now().date() - timedelta(days=int(max_age_days))
    stale = []
    for instrument_id in PortfolioUniverseInstrument.objects.filter(enabled=True, universe__enabled=True).values_list("instrument_id", flat=True).distinct():
        latest = InstrumentPriceHistory.objects.filter(instrument_id=instrument_id, provider="FINNHUB").order_by("-trading_date").first()
        if not latest or latest.trading_date < cutoff:
            stale.append(instrument_id)
    return stale

