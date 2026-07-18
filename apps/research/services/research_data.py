import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.broker_gateway.client import GatewayClient
from apps.instruments.models import BrokerContract, InstrumentProviderMapping
from apps.market_data.models import InstrumentPriceHistory
from apps.market_data.providers.finnhub import FinnhubClient

from ..models import ResearchCorporateAction, ResearchDailyBar


D = Decimal


@transaction.atomic
def stage_operational_history(instrument, *, provider="FINNHUB"):
    """Legacy operational history remains suspect until the full research validator runs."""
    created = 0
    for row in InstrumentPriceHistory.objects.filter(instrument=instrument, provider=provider).order_by("trading_date"):
        close = row.adjusted_close or row.close
        _, was_created = ResearchDailyBar.objects.get_or_create(
            instrument=instrument,
            trading_date=row.trading_date,
            data_version=row.data_version,
            defaults={
                "raw_open":row.open,"raw_high":row.high,"raw_low":row.low,"raw_close":row.close,
                "adjusted_open":row.open,"adjusted_high":row.high,"adjusted_low":row.low,
                "adjusted_close":close,"total_return_close":close,"volume":row.volume,
                "cash_dividend":0,"split_factor":1,"adjustment_factor":1,"provider":provider,
                "provider_timestamp":row.fetched_at,"revision_timestamp":row.fetched_at,
                "quality_status":"SUSPECT",
            },
        )
        created += int(was_created)
    return created


def _as_date(value):
    if isinstance(value,date):return value
    return date.fromisoformat(str(value)[:10])


def _at_utc_midnight(value):
    return datetime.combine(_as_date(value),time.min,tzinfo=dt_timezone.utc)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()


def _decimal_text(value):
    text=format(D(str(value)).normalize(),"f")
    return "0" if text in {"-0",""} else text


def _model_precision(values):
    price_fields={"raw_open","raw_high","raw_low","raw_close","adjusted_open","adjusted_high",
                  "adjusted_low","adjusted_close","total_return_close","cash_dividend"}
    result=dict(values)
    for key in price_fields:
        result[key]=D(result[key]).quantize(D("0.00000001"))
    result["volume"]=D(result["volume"]).quantize(D("0.0001"))
    result["split_factor"]=D(result["split_factor"]).quantize(D("0.0000000001"))
    result["adjustment_factor"]=D(result["adjustment_factor"]).quantize(D("0.0000000001"))
    return result


def _store_actions(instrument, actions, *, provider, revision_timestamp):
    stored=[]
    for action in actions:
        effective_at=_at_utc_midnight(action["effective_date"])
        announced_at=_at_utc_midnight(action["announced_date"]) if action.get("announced_date") else None
        payload=action.get("payload") or {}
        latest=ResearchCorporateAction.objects.filter(
            instrument=instrument,action_type=action["action_type"],effective_at=effective_at
        ).order_by("-data_version").first()
        version=latest.data_version if latest and _fingerprint(latest.payload)==_fingerprint(payload) else (
            latest.data_version + 1 if latest else 1
        )
        row,_=ResearchCorporateAction.objects.update_or_create(
            instrument=instrument,action_type=action["action_type"],effective_at=effective_at,data_version=version,
            defaults={"announced_at":announced_at,"payload":payload,"provider":provider,
                      "revision_timestamp":revision_timestamp,"quality_status":"VALID"},
        )
        stored.append(row)
    return stored


def _normalized_rows(raw_rows, actions, provider):
    dividends={_as_date(item["effective_date"]):D(str(item.get("payload",{}).get("amount",0)))
               for item in actions if item["action_type"]=="DIVIDEND"}
    splits={_as_date(item["effective_date"]):D(str(item.get("payload",{}).get("factor",1)))
            for item in actions if item["action_type"]=="SPLIT"}
    by_date={_as_date(item["trading_date"] if "trading_date" in item else item["date"]):item for item in raw_rows}
    future_split=D(1)
    normalized=[]
    for trading_date in sorted(by_date,reverse=True):
        item=by_date[trading_date]
        raw_open,raw_high=D(str(item["open"])),D(str(item["high"]))
        raw_low,raw_close=D(str(item["low"])),D(str(item["close"]))
        supplied_adjusted=item.get("adjusted_close")
        adjusted_close=D(str(supplied_adjusted)) if supplied_adjusted not in (None,"") else raw_close/future_split
        factor=raw_close/adjusted_close if adjusted_close else future_split
        adjusted_open,adjusted_high,adjusted_low=raw_open/factor,raw_high/factor,raw_low/factor
        dividend=dividends.get(trading_date,D(0))
        normalized.append({
            "trading_date":trading_date,"raw_open":raw_open,"raw_high":raw_high,"raw_low":raw_low,
            "raw_close":raw_close,"adjusted_open":adjusted_open,"adjusted_high":adjusted_high,
            "adjusted_low":adjusted_low,"adjusted_close":adjusted_close,
            "total_return_close":adjusted_close + (dividend/factor if factor else D(0)),
            "volume":D(str(item.get("volume",0))),"cash_dividend":dividend,
            "split_factor":splits.get(trading_date,D(1)),"adjustment_factor":factor,"provider":provider,
            "source_provider_timestamp":item.get("provider_timestamp"),
        })
        # Prices on the effective split date are already post-split; adjust only earlier observations.
        future_split *= splits.get(trading_date,D(1))
    rows=list(reversed(normalized));total_level=None;previous_adjusted=None
    for row in rows:
        adjusted_dividend=row["cash_dividend"]/row["adjustment_factor"] if row["adjustment_factor"] else D(0)
        if previous_adjusted is None:
            total_level=row["adjusted_close"]
        else:
            total_level*=((row["adjusted_close"]+adjusted_dividend)/previous_adjusted)
        row["total_return_close"]=total_level
        previous_adjusted=row["adjusted_close"]
    return rows


@transaction.atomic
def store_research_history(instrument, raw_rows, actions, *, provider, provider_timestamp=None):
    provider_timestamp=provider_timestamp or timezone.now()
    revision_timestamp=timezone.now()
    _store_actions(instrument,actions,provider=provider,revision_timestamp=revision_timestamp)
    written=0
    for values in _normalized_rows(raw_rows,actions,provider):
        values=_model_precision(values)
        comparable={key:_decimal_text(value) for key,value in values.items()
                    if key not in {"trading_date","provider","source_provider_timestamp"}}
        latest=ResearchDailyBar.objects.filter(
            instrument=instrument,trading_date=values["trading_date"]
        ).order_by("-data_version").first()
        latest_values={key:_decimal_text(getattr(latest,key)) for key in comparable} if latest else None
        version=latest.data_version if latest and latest.provider==provider and latest_values==comparable else (
            latest.data_version+1 if latest else 1
        )
        _,created=ResearchDailyBar.objects.update_or_create(
            instrument=instrument,trading_date=values["trading_date"],data_version=version,
            defaults={**{key:value for key,value in values.items() if key!="source_provider_timestamp"},
                      "provider_timestamp":values.get("source_provider_timestamp") or provider_timestamp,
                      "revision_timestamp":revision_timestamp,"quality_status":"PENDING"},
        )
        written += int(created)
    return written


def validate_research_history(instrument, *, minimum_bars=756, as_of_date=None,
                              maximum_missing_session_ratio=0.08):
    as_of_date=as_of_date or timezone.localdate()
    latest={}
    for row in ResearchDailyBar.objects.filter(instrument=instrument,trading_date__lte=as_of_date).order_by(
        "trading_date","-data_version"
    ):
        latest.setdefault(row.trading_date,row)
    rows=[latest[key] for key in sorted(latest)]
    reasons=[]
    structural=[]
    mapping=InstrumentProviderMapping.objects.filter(
        instrument=instrument,provider="FINNHUB",status="VERIFIED"
    ).first()
    if not mapping:reasons.append("FINNHUB_MAPPING_MISSING")
    if len(rows)<int(minimum_bars):reasons.append("INSUFFICIENT_VALID_HISTORY")
    for row in rows:
        prices=[row.raw_open,row.raw_high,row.raw_low,row.raw_close,row.adjusted_open,row.adjusted_high,
                row.adjusted_low,row.adjusted_close,row.total_return_close]
        if any(value is None or value<=0 for value in prices):structural.append("NON_POSITIVE_OHLC")
        if row.raw_low>min(row.raw_open,row.raw_close) or row.raw_high<max(row.raw_open,row.raw_close) or row.raw_low>row.raw_high:
            structural.append("INCONSISTENT_OHLC")
        if row.adjusted_low>min(row.adjusted_open,row.adjusted_close) or row.adjusted_high<max(row.adjusted_open,row.adjusted_close):
            structural.append("INCONSISTENT_ADJUSTED_OHLC")
        if row.volume<0:structural.append("NEGATIVE_VOLUME")
        if row.revision_timestamp>timezone.now():structural.append("FUTURE_REVISION")
    if rows:
        latest_date=rows[-1].trading_date
        if latest_date>as_of_date:structural.append("FUTURE_BAR")
        if latest_date<as_of_date-timedelta(days=7):reasons.append("STALE_DATA")
        expected=sum(1 for offset in range((latest_date-rows[0].trading_date).days+1)
                     if (rows[0].trading_date+timedelta(days=offset)).weekday()<5)
        missing_ratio=max(0,(expected-len(rows))/expected) if expected else 1
        if missing_ratio>maximum_missing_session_ratio:reasons.append("MISSING_SESSION_RATIO_EXCEEDED")
    else:
        latest_date=None;missing_ratio=1
    action_dates=set(ResearchCorporateAction.objects.filter(
        instrument=instrument,quality_status="VALID",action_type__in=["DIVIDEND","SPLIT"]
    ).values_list("effective_at__date",flat=True))
    trading_dates=set(latest)
    for action_date in action_dates:
        if not any(action_date+timedelta(days=offset) in trading_dates for offset in range(6)):
            reasons.append("CORPORATE_ACTION_NOT_RECONCILED");break
    reasons=list(dict.fromkeys(structural+reasons))
    status="REJECTED" if structural else "SUSPECT" if reasons else "VALID"
    if rows:
        ResearchDailyBar.objects.filter(pk__in=[row.pk for row in rows]).update(quality_status=status)
    return {"status":status,"reasons":reasons,"valid_bar_count":len(rows) if status=="VALID" else 0,
            "bar_count":len(rows),"latest_date":latest_date.isoformat() if latest_date else None,
            "missing_session_ratio":missing_ratio,
            "provider":rows[-1].provider if rows else None,"provider_symbol":mapping.provider_symbol if mapping else None}


def _gateway_rows(instrument, contract, *, years, gateway=None):
    response=(gateway or GatewayClient()).historical_bars({
        "conid":contract.conid,"symbol":instrument.symbol,"exchange":instrument.exchange,
        "currency":instrument.currency,"bar_size":"1 day","duration":f"{years} Y",
        "what_to_show":"ADJUSTED_LAST","use_rth":True,"end_time":"",
    })
    return [{**row,"trading_date":_as_date(row["date"]),"adjusted_close":row["close"],
             "provider_timestamp":_at_utc_midnight(row["date"])}
            for row in response.get("bars",[])]


def refresh_research_history(instrument, *, years=5, minimum_bars=756, finnhub=None, gateway=None,
                             as_of_date=None):
    as_of_date=as_of_date or timezone.localdate()
    start_date=as_of_date-timedelta(days=int(years)*366)
    mapping=InstrumentProviderMapping.objects.filter(
        instrument=instrument,provider="FINNHUB",status="VERIFIED"
    ).first()
    if not mapping:
        return validate_research_history(instrument,minimum_bars=minimum_bars,as_of_date=as_of_date)
    primary_error=None
    try:
        client=finnhub or FinnhubClient()
        raw=client.daily_candles(mapping.provider_symbol,start_date,as_of_date)
        actions=client.corporate_actions(mapping.provider_symbol,start_date,as_of_date)
        raw=[{key:value for key,value in row.items() if key!="adjusted_close"} for row in raw]
        store_research_history(instrument,raw,actions,provider="FINNHUB")
    except Exception as exc:
        primary_error=str(exc)
        contract=BrokerContract.objects.filter(instrument=instrument,qualified_at__isnull=False).first()
        if contract:
            raw=_gateway_rows(instrument,contract,years=years,gateway=gateway)
            store_research_history(instrument,raw,[],provider="IBKR_ADJUSTED_LAST")
    report=validate_research_history(instrument,minimum_bars=minimum_bars,as_of_date=as_of_date)
    if primary_error:report["primary_error"]=primary_error
    return report
