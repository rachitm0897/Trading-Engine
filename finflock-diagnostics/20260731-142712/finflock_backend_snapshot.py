import json, traceback
from datetime import date, datetime
from decimal import Decimal
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import Max
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone

SENSITIVE = ('password','secret','token','credential','authorization','api_key','encrypted','private_key')

def sensitive(name):
    text = str(name or '').lower()
    return any(part in text for part in SENSITIVE)

def safe(value, depth=0):
    if depth > 5: return '<max-depth>'
    if isinstance(value, dict):
        return {str(k): ('[REDACTED]' if sensitive(k) else safe(v, depth+1)) for k,v in value.items()}
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        out = [safe(v, depth+1) for v in values[:100]]
        if len(values) > 100: out.append(f'<{len(values)-100} more>')
        return out
    if isinstance(value, (datetime, date, Decimal)): return str(value)
    if isinstance(value, bytes): return f'<bytes:{len(value)}>'
    if isinstance(value, str) and len(value) > 8000: return value[:8000] + '<truncated>'
    return value

def emit(title, payload):
    print(f'\n===== {title} =====')
    print(json.dumps(safe(payload), indent=2, sort_keys=True, default=str))

def model(label):
    try: return apps.get_model(label)
    except Exception as exc:
        emit(f'MODEL LOOKUP FAILED {label}', {'error': repr(exc)})
        return None

def row(obj):
    data = {}
    for field in obj._meta.concrete_fields:
        name = field.attname
        data[name] = '[REDACTED]' if sensitive(name) else safe(getattr(obj, name, None))
    return data

def dump(label, limit=20, filters=None):
    m = model(label)
    if not m: return
    try:
        qs = m.objects.all()
        if filters: qs = qs.filter(**filters)
        pk = m._meta.pk.name
        emit(label, {'count': qs.count(), 'filters': filters or {}, 'latest_rows': [row(x) for x in qs.order_by(f'-{pk}')[:limit]]})
    except Exception as exc:
        emit(f'DUMP FAILED {label}', {'error': repr(exc), 'traceback': traceback.format_exc()})

emit('DATABASE', {'vendor': connection.vendor, 'name': connection.settings_dict.get('NAME'), 'host': connection.settings_dict.get('HOST'), 'port': connection.settings_dict.get('PORT'), 'time': timezone.now()})

setting_names = (
    'ALLOW_LIVE_TRADING','GLOBAL_KILL_SWITCH','KAFKA_ENABLED','KAFKA_BOOTSTRAP_SERVERS','FLINK_REST_URL',
    'MARKET_PRICE_STALE_SECONDS','MARKET_DATA_FALLBACK_ENABLED','FINNHUB_HISTORICAL_FALLBACK_ENABLED',
    'FINNHUB_LIVE_FALLBACK_ENABLED','FINNHUB_AUTO_FAILBACK_ENABLED','FINNHUB_API_KEY_OVERRIDE_ENABLED',
    'RESEARCH_ENABLED','RECOMMENDATION_SYSTEM_ENABLED','RECOMMENDATION_UNIVERSE_KEY','RECOMMENDATION_MIN_STOCKS',
    'RECOMMENDATION_MAX_STOCKS','RESEARCH_MINIMUM_DAILY_BARS','RESEARCH_SCORE_MAX_AGE_DAYS',
    'RECOMMENDATION_SNAPSHOT_MAX_AGE_HOURS','LOCAL_PAPER_GATEWAY_URL','LOCAL_PAPER_GATEWAY_CONTAINER_NAME',
    'EXECUTION_ACTIVATION_PREFLIGHT_ENABLED')
emit('SELECTED SETTINGS', {name: getattr(settings, name, '<not-defined>') for name in setting_names})

def walk(patterns, prefix=''):
    for item in patterns:
        try:
            current = prefix + str(item.pattern)
            if isinstance(item, URLPattern):
                yield current, getattr(item.callback, '__module__', ''), getattr(item.callback, '__name__', '')
            elif isinstance(item, URLResolver):
                yield from walk(item.url_patterns, current)
        except Exception as exc:
            yield f'<route-error:{exc!r}>', '', ''
terms = ('research','recommend','portfolio','construction','readiness','market','execution','broker')
routes = [{'route':r,'view':f'{m}.{n}'.strip('.')} for r,m,n in walk(get_resolver().url_patterns) if any(t in r.lower() for t in terms)]
emit('RELEVANT URL ROUTES', routes)

try:
    Coverage = model('research.ResearchDataCoverageSummary')
    Bars = model('research.ResearchDailyBar')
    Features = model('research.InstrumentFeatureSnapshot')
    Caches = model('research.RecommendationCacheSnapshot')
    now = timezone.now()
    metrics = {}
    if Coverage:
        metrics.update(coverage_rows=Coverage.objects.count(), coverage_ready=Coverage.objects.filter(recommendation_eligible=True).count(), coverage_latest=Coverage.objects.aggregate(v=Max('as_of_date'))['v'])
    if Bars:
        metrics.update(daily_bars_total=Bars.objects.count(), daily_bars_valid=Bars.objects.filter(quality_status='VALID').count(), daily_bar_instruments_valid=Bars.objects.filter(quality_status='VALID').values('instrument_id').distinct().count(), daily_bars_latest=Bars.objects.aggregate(v=Max('trading_date'))['v'])
    if Features:
        metrics.update(feature_snapshots_total=Features.objects.count(), feature_instruments=Features.objects.values('instrument_id').distinct().count(), feature_latest=Features.objects.aggregate(v=Max('as_of_date'))['v'])
    if Caches:
        metrics.update(caches_total=Caches.objects.count(), caches_completed_unexpired=Caches.objects.filter(status='COMPLETED', expires_at__gt=now).count(), caches_latest=Caches.objects.aggregate(v=Max('created_at'))['v'])
    emit('PORTFOLIO BUILDER RESEARCH METRICS', metrics)
except Exception as exc:
    emit('PORTFOLIO BUILDER METRICS FAILED', {'error': repr(exc), 'traceback': traceback.format_exc()})

for label, limit in [
    ('research.ResearchDatasetVersion',10),('research.ResearchUniverse',10),('research.ResearchUniverseMember',10),
    ('research.ResearchDataCoverageSummary',20),('research.ResearchDailyBar',20),('research.InstrumentFeatureSnapshot',20),
    ('research.ResearchStrategyReadiness',20),('research.GoalRecommendationPolicy',20),('research.RecommendationCacheSnapshot',20),
    ('research.RecommendationBatchRun',20),('research.GoalRecommendationRun',20),
    ('portfolio_construction.StrategyConstructionProfile',20),('portfolio_construction.PortfolioConstructionPlan',20),
    ('portfolio_construction.PortfolioGoalAllocation',20),('market_data.MarketDataProviderConfiguration',10),
    ('instruments.InstrumentProviderMapping',30),('broker_gateway.BrokerGatewaySession',10),('accounts.BrokerAccount',10),
    ('portfolios.TradingPortfolio',20),('market_streams.MarketDataSubscription',50),('market_streams.InstrumentMarketState',50),
    ('market_streams.MarketBar',50),('market_streams.IndicatorValue',50),('strategies.StrategyInstance',30),
    ('strategies.StrategyAction',30),('strategies.StrategyRun',30),('oms.OrderIntent',50),('oms.Order',50),
    ('execution.BrokerCommand',50),('execution.Fill',50),('risk.RiskCheckResult',50),('audit.OutboxEvent',100)]:
    dump(label, limit)

try:
    Instrument = model('instruments.Instrument')
    instruments = list(Instrument.objects.filter(symbol__iexact='BLK')) if Instrument else []
    emit('BLK INSTRUMENTS', [row(x) for x in instruments])
    for instrument in instruments:
        for label, limit in [('market_streams.InstrumentMarketState',10),('market_streams.MarketDataSubscription',20),('market_streams.MarketBar',100),('market_streams.IndicatorValue',100),('instruments.InstrumentProviderMapping',20)]:
            dump(label, limit, {'instrument_id': instrument.pk})
except Exception as exc:
    emit('BLK SNAPSHOT FAILED', {'error': repr(exc), 'traceback': traceback.format_exc()})
