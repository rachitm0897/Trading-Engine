from django.db import transaction

from apps.market_data.models import InstrumentPriceHistory

from ..models import ResearchDailyBar


@transaction.atomic
def stage_operational_history(instrument, *, provider="FINNHUB"):
    """Stage operational closes as SUSPECT; never mislabel them research-grade adjusted data."""
    created = 0
    for row in InstrumentPriceHistory.objects.filter(instrument=instrument, provider=provider).order_by("trading_date"):
        close = row.adjusted_close or row.close
        _, was_created = ResearchDailyBar.objects.get_or_create(
            instrument=instrument,
            trading_date=row.trading_date,
            data_version=row.data_version,
            defaults={
                "raw_open": row.open,
                "raw_high": row.high,
                "raw_low": row.low,
                "raw_close": row.close,
                "adjusted_open": row.open,
                "adjusted_high": row.high,
                "adjusted_low": row.low,
                "adjusted_close": close,
                "total_return_close": close,
                "volume": row.volume,
                "cash_dividend": 0,
                "split_factor": 1,
                "adjustment_factor": 1,
                "provider": provider,
                "provider_timestamp": row.fetched_at,
                "revision_timestamp": row.fetched_at,
                "quality_status": "SUSPECT",
            },
        )
        created += int(was_created)
    return created
