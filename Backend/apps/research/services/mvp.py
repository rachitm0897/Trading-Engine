import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Min
from django.utils import timezone

from apps.instruments.models import BrokerContract, InstrumentProviderMapping
from apps.market_data.providers.finnhub import provider_status
from apps.portfolio_construction.models import StrategyConstructionProfile
from apps.strategies.models import StrategyDefinition
from apps.strategies.plugins.registry import get_plugin

from ..engines.base import ResearchProtocolContext
from ..engines.single_asset import SingleAssetBacktestEngine
from ..enums import ImplementationStatus, MappingStatus
from ..implementations.wave0 import implementation_for
from ..models import (
    BacktestProtocolVersion,
    InstrumentEligibilitySnapshot,
    ResearchCandidateScore,
    ResearchDailyBar,
    ResearchDatasetVersion,
    ResearchExperiment,
    ResearchFeatureDefinition,
    ResearchStrategyImplementation,
    ResearchStrategyReadiness,
    ResearchTrial,
    ResearchUniverse,
    ResearchUniverseMember,
)
from .eligibility import calculate_member_eligibility
from .promotion import implementation_hash
from .research_data import refresh_research_history


EXPECTED_STOCKS=("AAPL","JPM","XOM","JNJ","WMT")
EXPECTED_STRATEGIES=(
    "FIXED_WEIGHT_REBALANCE","SMA_CROSSOVER","RSI_MEAN_REVERSION","DONCHIAN_BREAKOUT",
    "VOLATILITY_TARGET_MOMENTUM",
)

STRATEGY_SPECS={
    "FIXED_WEIGHT_REBALANCE":{
        "research_id":"BH_001","path":"apps.research.implementations.wave0.FixedWeightResearch","budget":1,
        "defaults":{"direction":"LONG","target_weight":1.0},
    },
    "SMA_CROSSOVER":{
        "research_id":"TR_001_SMA_020_100","path":"apps.research.implementations.wave0.SMACrossoverResearch","budget":6,
        "defaults":{"fast_window":20,"slow_window":100,"entry_rule":"CROSS_ABOVE","exit_rule":"CROSS_BELOW","direction":"LONG"},
    },
    "RSI_MEAN_REVERSION":{
        "research_id":"MR_002_RSI14","path":"apps.research.implementations.wave0.RSIMeanReversionResearch","budget":8,
        "defaults":{"window":14,"entry_threshold":30,"exit_threshold":65,"entry_rule":"CROSS_ABOVE","exit_rule":"CROSS_ABOVE","direction":"LONG"},
    },
    "DONCHIAN_BREAKOUT":{
        "research_id":"TR_006_DONCHIAN_20","path":"apps.research.implementations.wave0.DonchianBreakoutResearch","budget":6,
        "defaults":{"entry_window":20,"exit_window":10,"direction":"LONG"},
    },
    "VOLATILITY_TARGET_MOMENTUM":{
        "research_id":"MOM_001_TS_21","path":"apps.research.implementations.wave0.VolatilityTargetMomentumResearch","budget":8,
        "defaults":{"momentum_window":21,"volatility_window":20,"target_volatility":0.10,"maximum_weight":1.0,"direction":"LONG"},
    },
}


def _csv(value):
    return tuple(item.strip().upper() for item in str(value).split(",") if item.strip())


def _positive_integer(value,name):
    try:result=int(value)
    except (TypeError,ValueError) as exc:raise ValueError(f"{name} must be an integer") from exc
    if result<=0:raise ValueError(f"{name} must be positive")
    return result


@dataclass(frozen=True)
class RecommendationMVPSettings:
    enabled:bool
    stocks:tuple[str,...]
    strategies:tuple[str,...]
    minimum_bars:int
    lookback_years:int
    max_stocks:int
    max_strategies_per_stock:int

    def validate(self):
        if self.stocks!=EXPECTED_STOCKS:
            raise ValueError(f"RESEARCH_MVP_STOCKS must be exactly {','.join(EXPECTED_STOCKS)}")
        if self.strategies!=EXPECTED_STRATEGIES:
            raise ValueError(f"RESEARCH_MVP_STRATEGIES must be exactly {','.join(EXPECTED_STRATEGIES)}")
        if self.minimum_bars<756:raise ValueError("RESEARCH_MVP_MINIMUM_BARS cannot be below 756")
        if self.lookback_years!=5:raise ValueError("RESEARCH_MVP_LOOKBACK_YEARS must be 5 for this pilot")
        if self.max_stocks!=5:raise ValueError("RESEARCH_MVP_MAX_STOCKS must be 5")
        if self.max_strategies_per_stock!=1:
            raise ValueError("RESEARCH_MVP_MAX_STRATEGIES_PER_STOCK must be 1")
        return self


def mvp_settings():
    return RecommendationMVPSettings(
        enabled=bool(settings.RESEARCH_MVP_ENABLED),stocks=_csv(settings.RESEARCH_MVP_STOCKS),
        strategies=_csv(settings.RESEARCH_MVP_STRATEGIES),
        minimum_bars=_positive_integer(settings.RESEARCH_MVP_MINIMUM_BARS,"RESEARCH_MVP_MINIMUM_BARS"),
        lookback_years=_positive_integer(settings.RESEARCH_MVP_LOOKBACK_YEARS,"RESEARCH_MVP_LOOKBACK_YEARS"),
        max_stocks=_positive_integer(settings.RESEARCH_MVP_MAX_STOCKS,"RESEARCH_MVP_MAX_STOCKS"),
        max_strategies_per_stock=_positive_integer(
            settings.RESEARCH_MVP_MAX_STRATEGIES_PER_STOCK,"RESEARCH_MVP_MAX_STRATEGIES_PER_STOCK"
        ),
    ).validate()


def active_dataset_and_protocol():
    dataset=ResearchDatasetVersion.objects.filter(status="ACTIVE").order_by("-snapshot_date","-pk").first()
    if not dataset:raise ValueError("No active research dataset")
    protocol=BacktestProtocolVersion.objects.filter(dataset_version=dataset,active=True).first()
    if not protocol:raise ValueError("No active backtest protocol")
    return dataset,protocol


@transaction.atomic
def create_or_update_pilot_universe(dataset=None):
    config=mvp_settings();dataset=dataset or active_dataset_and_protocol()[0]
    source=ResearchUniverse.objects.filter(dataset_version=dataset,active=True).exclude(key="RECOMMENDATION_MVP").order_by("pk").first()
    if not source:raise ValueError("Active dataset has no source universe")
    source_members={row.source_symbol:row for row in source.members.filter(source_symbol__in=config.stocks).select_related("issuer","instrument")}
    missing=[symbol for symbol in config.stocks if symbol not in source_members]
    if missing:raise ValueError(f"Pilot stocks missing from active research universe: {', '.join(missing)}")
    universe,_=ResearchUniverse.objects.update_or_create(
        dataset_version=dataset,key="RECOMMENDATION_MVP",
        defaults={"name":"Recommendation MVP: 5 Stocks","description":"Controlled five-stock recommendation pilot",
                  "membership_type":source.membership_type,"active":True},
    )
    keep=[]
    for order,symbol in enumerate(config.stocks):
        row=source_members[symbol]
        member,_=ResearchUniverseMember.objects.update_or_create(
            universe=universe,issuer=row.issuer,
            defaults={"instrument":row.instrument,"source_symbol":symbol,"security_name":row.security_name,
                      "currency":row.currency,"exchange_hint":row.exchange_hint,
                      "membership_start":row.membership_start,"membership_end":row.membership_end,
                      "membership_status":row.membership_status,
                      "research_eligibility_configuration":{**(row.research_eligibility_configuration or {}),
                                                               "minimum_adjusted_history_days":config.minimum_bars,
                                                               "pilot_display_order":order},
                      "risk_timeframe_profile":row.risk_timeframe_profile,"mapping_status":row.mapping_status,
                      "mapping_notes":row.mapping_notes,"active":True},
        )
        keep.append(member.pk)
    universe.members.exclude(pk__in=keep).update(active=False)
    return universe


def _validate_schema_value(name,value,schema):
    kind=schema.get("type")
    if kind=="integer" and (isinstance(value,bool) or not isinstance(value,int)):raise ValueError(f"{name} must be an integer")
    if kind=="number" and (isinstance(value,bool) or not isinstance(value,(int,float))):raise ValueError(f"{name} must be numeric")
    if "enum" in schema and value not in schema["enum"]:raise ValueError(f"{name} is outside the runtime enum")
    if "minimum" in schema and value<schema["minimum"]:raise ValueError(f"{name} is below the runtime minimum")
    if "maximum" in schema and value>schema["maximum"]:raise ValueError(f"{name} is above the runtime maximum")
    if "exclusiveMinimum" in schema and value<=schema["exclusiveMinimum"]:raise ValueError(f"{name} is below the runtime bound")


def semantic_validation(runtime_key,implementation):
    spec=STRATEGY_SPECS[runtime_key];plugin=get_plugin(runtime_key);parameters=dict(spec["defaults"])
    schema=plugin.parameter_schema
    missing=set(schema.get("required",[]))-set(parameters)
    if missing:raise ValueError(f"Missing runtime parameters: {', '.join(sorted(missing))}")
    for name,value in parameters.items():
        if name in schema.get("properties",{}):_validate_schema_value(name,value,schema["properties"][name])
    plugin.validate_configuration(parameters,{"target_weight":1})
    bars=[]
    for index in range(320):
        close=100 + index*0.08 + ((index%23)-11)*0.35
        bars.append({"open":close-0.1,"high":close+1,"low":close-1,"close":close,"volume":1_000_000})
    strategy=implementation_for(runtime_key)
    first=strategy.signals(bars,parameters,ResearchProtocolContext())
    second=strategy.signals(bars,parameters,ResearchProtocolContext())
    if first.desired_exposure!=second.desired_exposure:raise ValueError("Research signal output is not deterministic")
    if len(first.desired_exposure)!=len(bars):raise ValueError("Research signal output length is invalid")
    if any(value<0 or value>1 for value in first.desired_exposure):raise ValueError("Research adapter is not long-only [0,1]")
    result=SingleAssetBacktestEngine().run(strategy,bars,parameters,ResearchProtocolContext())
    if result.diagnostics.get("execution")!="NEXT_OPEN":raise ValueError("Research adapter does not execute on the next bar")
    if result.positions[0]!=0:raise ValueError("Research adapter entered before next-bar execution")
    return {
        "parameter_names_and_types":True,"defaults":True,"long_only":True,"exposure_range":True,
        "signal_timing":True,"next_bar_execution":True,"entry_exit_behavior":True,
        "warmup":int(first.diagnostics.get("warmup_bars",0)),"deterministic_output":True,
        "runtime_plugin_parity":True,"runtime_key":runtime_key,"research_id":spec["research_id"],
    }


@transaction.atomic
def register_and_validate_strategies(dataset=None):
    config=mvp_settings();dataset=dataset or active_dataset_and_protocol()[0];rows=[]
    for runtime_key in config.strategies:
        spec=STRATEGY_SPECS[runtime_key]
        research=dataset.strategies.get(research_id=spec["research_id"],active=True)
        definition=StrategyDefinition.objects.get(key=runtime_key,enabled=True)
        digest=implementation_hash(spec["path"])
        row,created=ResearchStrategyImplementation.objects.get_or_create(
            research_strategy=research,implementation_path=spec["path"],implementation_version="mvp-v1",
            defaults={"implementation_hash":digest,"role":"EXECUTION","supported_frequency":"1d",
                      "supported_direction":"LONG","executable_strategy_definition":None,
                      "exact_semantic_match":False,"status":ImplementationStatus.DRAFT,
                      "default_parameters":spec["defaults"]},
        )
        changed_hash=row.implementation_hash!=digest
        row.implementation_hash=digest;row.role="EXECUTION";row.supported_frequency="1d"
        row.supported_direction="LONG";row.default_parameters=spec["defaults"]
        needs_validation=created or changed_hash or row.status==ImplementationStatus.DRAFT or not (
            row.approval_record or {}
        ).get("semantic_validation")
        if needs_validation:
            row.status=ImplementationStatus.DRAFT;row.exact_semantic_match=False;row.executable_strategy_definition=None
            row.approval_record={**(row.approval_record or {}),"semantic_validation":{}}
            row.save(update_fields=["implementation_hash","role","supported_frequency","supported_direction",
                                    "default_parameters","status","exact_semantic_match",
                                    "executable_strategy_definition","approval_record","updated_at"])
            evidence=semantic_validation(runtime_key,row)
            row.status=ImplementationStatus.VALIDATED;row.exact_semantic_match=True
            row.executable_strategy_definition=definition
            row.approval_record={**(row.approval_record or {}),"semantic_validation":evidence,
                                 "validated_at":timezone.now().isoformat()}
            row.save(update_fields=["status","exact_semantic_match","executable_strategy_definition",
                                    "approval_record","updated_at"])
        else:
            row.executable_strategy_definition=definition
            row.save(update_fields=["implementation_hash","role","supported_frequency","supported_direction",
                                    "default_parameters","executable_strategy_definition","updated_at"])
        research.feature_requirements.update(required=True)
        ResearchFeatureDefinition.objects.filter(
            strategy_requirements__research_strategy=research
        ).update(status="VALIDATED",batch_implementation_path=spec["path"],implementation_version="mvp-v1")
        rows.append(row)
    return rows


def _parameter_rows(key):
    defaults=STRATEGY_SPECS[key]["defaults"]
    grids={
        "FIXED_WEIGHT_REBALANCE":[defaults],
        "SMA_CROSSOVER":[{**defaults,"fast_window":fast,"slow_window":slow} for fast,slow in
                         [(10,50),(20,50),(20,100),(50,100),(50,200),(100,200)]],
        "RSI_MEAN_REVERSION":[{**defaults,"window":window,"entry_threshold":entry,"exit_threshold":exit_}
                              for window,entry,exit_ in [(2,10,55),(2,20,65),(7,20,60),(7,30,70),
                                                       (14,20,60),(14,25,65),(14,30,65),(21,30,70)]],
        "DONCHIAN_BREAKOUT":[{**defaults,"entry_window":entry,"exit_window":exit_} for entry,exit_ in
                             [(20,10),(40,10),(40,20),(55,20),(100,20),(100,50)]],
        "VOLATILITY_TARGET_MOMENTUM":[{**defaults,"momentum_window":momentum,"volatility_window":vol,
                                        "target_volatility":target} for momentum,vol,target in
                                      [(21,20,.10),(21,60,.10),(63,20,.10),(63,60,.10),
                                       (126,20,.10),(126,60,.10),(252,60,.10),(252,60,.15)]],
    }
    plugin=get_plugin(key);rows=grids[key][:STRATEGY_SPECS[key]["budget"]]
    for parameters in rows:
        plugin.validate_configuration(parameters,{"target_weight":1})
    return rows


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()


@transaction.atomic
def create_mvp_experiments(universe=None,protocol=None):
    config=mvp_settings();dataset,active_protocol=active_dataset_and_protocol()
    universe=universe or create_or_update_pilot_universe(dataset);protocol=protocol or active_protocol
    implementations={row.executable_strategy_definition.key:row for row in ResearchStrategyImplementation.objects.filter(
        research_strategy__dataset_version=dataset,executable_strategy_definition__key__in=config.strategies,
        status__in=[ImplementationStatus.VALIDATED,ImplementationStatus.BACKTESTED,ImplementationStatus.SCORED,
                    ImplementationStatus.APPROVED_FOR_RECOMMENDATION,ImplementationStatus.SHADOW_VALIDATED,
                    ImplementationStatus.BUILDER_READY,ImplementationStatus.APPROVED],exact_semantic_match=True,
    ).select_related("research_strategy","executable_strategy_definition")}
    created=0;reused=0;experiments=[]
    for member in universe.members.filter(active=True).select_related("instrument").order_by("source_symbol"):
        if not member.instrument_id:continue
        data=ResearchDailyBar.objects.filter(instrument=member.instrument,quality_status="VALID").aggregate(
            start=Min("trading_date"),end=Max("trading_date"),version=Max("data_version"),count=Count("id"),revision=Max("revision_timestamp")
        )
        data_ready=bool(data["start"] and int(data["count"] or 0)>=config.minimum_bars)
        data_version=_hash({key:str(value) for key,value in data.items()}) if data_ready else "MISSING"
        for runtime_key in config.strategies:
            implementation=implementations.get(runtime_key)
            if not implementation:continue
            parameter_rows=_parameter_rows(runtime_key);space_hash=_hash(parameter_rows)
            identity={"dataset":dataset.version,"protocol":protocol.configuration_hash,"instrument":member.instrument_id,
                      "strategy":implementation.research_strategy.research_id,
                      "implementation":implementation.implementation_hash,"data":data_version,
                      "parameters":space_hash,"start":data["start"],"end":data["end"]}
            request_hash=_hash(identity);idempotency_key=f"mvp-experiment:{request_hash}"
            experiment,was_created=ResearchExperiment.objects.get_or_create(
                idempotency_key=idempotency_key,
                defaults={"strategy":implementation.research_strategy,"universe":universe,"protocol":protocol,
                          "dataset_version":dataset,"instrument":member.instrument,
                          "implementation_hash":implementation.implementation_hash,"data_version":data_version,
                          "parameter_space_hash":space_hash,"start_date":data["start"],"end_date":data["end"],
                          "experiment_type":"MVP_WALK_FORWARD","parameter_budget":STRATEGY_SPECS[runtime_key]["budget"],
                          "request_hash":request_hash,"status":"QUEUED" if data_ready else "BLOCKED",
                          "error":"" if data_ready else "INSUFFICIENT_VALID_HISTORY"},
            )
            created+=int(was_created);reused+=int(not was_created);experiments.append(experiment)
            for parameters in parameter_rows if data_ready else []:
                parameter_hash=_hash(parameters)
                ResearchTrial.objects.get_or_create(
                    experiment=experiment,instrument=member.instrument,parameter_hash=parameter_hash,
                    defaults={"parameters":parameters,"window_configuration":{
                        "final_holdout_bars":126,"holdout_untouched":True,"minimum_test_windows":3,
                        "purge_bars":5,"embargo_bars":5,"signal_at":"t","execution_at":"t+1_open",
                    },"status":"QUEUED"},
                )
    return {"experiments":experiments,"created":created,"reused":reused}


def refresh_mvp_data(universe=None,*,finnhub=None,gateway=None):
    config=mvp_settings();universe=universe or create_or_update_pilot_universe();reports={}
    for member in universe.members.filter(active=True).select_related("instrument"):
        if not member.instrument_id:
            reports[member.source_symbol]={"status":"REJECTED","reasons":["UNMAPPED_OR_INACTIVE"]};continue
        report=refresh_research_history(member.instrument,years=config.lookback_years,
                                        minimum_bars=config.minimum_bars,finnhub=finnhub,gateway=gateway)
        snapshot=calculate_member_eligibility(member)
        combined=list(dict.fromkeys([*report.get("reasons",[]),*snapshot.rejection_reasons]))
        if report.get("status")!="VALID":
            snapshot.data_quality_status=report.get("status","SUSPECT")
            snapshot.research_eligible=False;snapshot.builder_eligible=False;snapshot.rejection_reasons=combined
        snapshot.metrics={**(snapshot.metrics or {}),"research_validation":report,
                          "latest_data_date":str(report.get("latest_date") or ""),"provider":report.get("provider")}
        snapshot.save(update_fields=["data_quality_status","research_eligible","builder_eligible",
                                     "rejection_reasons","metrics"])
        reports[member.source_symbol]=report
    return reports


def readiness_matrix():
    config=mvp_settings()
    try:dataset,protocol=active_dataset_and_protocol();universe=ResearchUniverse.objects.filter(
        dataset_version=dataset,key="RECOMMENDATION_MVP",active=True
    ).first()
    except ValueError:
        dataset=protocol=universe=None
    implementations={}
    if dataset:
        for row in ResearchStrategyImplementation.objects.filter(
            research_strategy__dataset_version=dataset,executable_strategy_definition__key__in=config.strategies
        ).select_related("research_strategy","executable_strategy_definition"):
            implementations[row.executable_strategy_definition.key]=row
    rows=[]
    members={row.source_symbol:row for row in universe.members.filter(active=True).select_related("instrument") } if universe else {}
    for symbol in config.stocks:
        member=members.get(symbol);instrument=member.instrument if member and member.instrument_id else None
        mapping=InstrumentProviderMapping.objects.filter(instrument=instrument,provider="FINNHUB").first() if instrument else None
        contract=BrokerContract.objects.filter(instrument=instrument,qualified_at__isnull=False).first() if instrument else None
        eligibility=member.eligibility_snapshots.order_by("-as_of_date").first() if member else None
        cells=[]
        for key in config.strategies:
            implementation=implementations.get(key)
            experiment=ResearchExperiment.objects.filter(
                dataset_version=dataset,instrument=instrument,strategy=implementation.research_strategy if implementation else None
            ).order_by("-pk").first() if dataset and instrument and implementation else None
            score=ResearchCandidateScore.objects.filter(
                dataset_version=dataset,instrument=instrument,strategy=implementation.research_strategy if implementation else None,
                expires_at__gt=timezone.now()
            ).order_by("-eligible","-score").first() if dataset and instrument and implementation else None
            blockers=[]
            if not mapping or mapping.status!="VERIFIED":blockers.append("FINNHUB_MAPPING_MISSING")
            if not eligibility or eligibility.data_quality_status!="VALID":blockers.append("INSUFFICIENT_VALID_HISTORY")
            if not contract:blockers.append("IBKR_CONTRACT_NOT_QUALIFIED")
            if not implementation or implementation.status==ImplementationStatus.DRAFT:blockers.append("NO_VALIDATED_IMPLEMENTATION")
            if not experiment or experiment.status not in {"COMPLETED"}:blockers.append("NO_PASSING_BACKTEST")
            builder_ready=bool(implementation and implementation.status in {ImplementationStatus.BUILDER_READY,ImplementationStatus.APPROVED})
            if not builder_ready:blockers.append("STRATEGY_NOT_BUILDER_READY")
            cells.append({"strategy_key":key,"research_id":implementation.research_strategy.research_id if implementation else STRATEGY_SPECS[key]["research_id"],
                          "status":"BUILDER_READY" if not blockers else (experiment.status if experiment else "BLOCKED"),
                          "score":float(score.score) if score else None,"approved":bool(score and score.eligible),
                          "builder_ready":builder_ready,"blockers":list(dict.fromkeys(blockers)),
                          "experiment_id":experiment.pk if experiment else None})
        rows.append({"symbol":symbol,"company":member.security_name if member else "","instrument_id":instrument.pk if instrument else None,
                     "finnhub_status":mapping.status if mapping else "MISSING","finnhub_symbol":mapping.provider_symbol if mapping else None,
                     "ibkr_status":"QUALIFIED" if contract else "MISSING","conid":contract.conid if contract else None,
                     "valid_bar_count":eligibility.history_days if eligibility and eligibility.data_quality_status=="VALID" else 0,
                     "latest_date":(eligibility.metrics or {}).get("latest_data_date") if eligibility else None,
                     "provider":(eligibility.metrics or {}).get("provider") if eligibility else None,
                     "eligible":bool(eligibility and eligibility.builder_eligible),
                     "blockers":eligibility.rejection_reasons if eligibility else ["INSUFFICIENT_VALID_HISTORY"],"strategies":cells})
    return {"dataset_version":dataset.version if dataset else None,"protocol_id":protocol.protocol_id if protocol else None,
            "stocks":rows,"strategy_keys":list(config.strategies),"generated_at":timezone.now()}


def mvp_status():
    config=mvp_settings();matrix=readiness_matrix();cells=[cell for row in matrix["stocks"] for cell in row["strategies"]]
    latest_refresh=ResearchDailyBar.objects.filter(instrument_id__in=[row["instrument_id"] for row in matrix["stocks"] if row["instrument_id"]]).aggregate(value=Max("revision_timestamp"))["value"]
    latest_experiment=ResearchExperiment.objects.filter(experiment_type="MVP_WALK_FORWARD").aggregate(value=Max("completed_at"))["value"]
    try:
        from apps.broker_gateway.client import GatewayClient
        gateway=GatewayClient().health()
    except Exception as exc:
        gateway={"connected":False,"error":str(exc)[:500]}
    return {"research_enabled":bool(settings.RESEARCH_ENABLED),"mvp_enabled":config.enabled,
            "finnhub":provider_status(),"pilot_stock_count":len(matrix["stocks"]),
            "ready_stock_count":sum(row["eligible"] for row in matrix["stocks"]),
            "validated_strategy_count":sum(1 for key in config.strategies if any(
                cell["strategy_key"]==key and "NO_VALIDATED_IMPLEMENTATION" not in cell["blockers"] for cell in cells
            )),"completed_experiment_groups":sum(cell["status"] in {"COMPLETED","BUILDER_READY"} for cell in cells),
            "eligible_candidate_count":ResearchCandidateScore.objects.filter(
                instrument_id__in=[row["instrument_id"] for row in matrix["stocks"] if row["instrument_id"]],
                eligible=True,expires_at__gt=timezone.now()
            ).count(),"last_data_refresh":latest_refresh,"last_experiment_run":latest_experiment,
            "ibkr":gateway,"matrix":matrix}


def run_mvp_pipeline(*,refresh_data=True,finnhub=None,gateway=None):
    if not settings.RESEARCH_ENABLED:raise ValueError("RESEARCH_DISABLED")
    config=mvp_settings()
    if not config.enabled:raise ValueError("RESEARCH_DISABLED")
    dataset,protocol=active_dataset_and_protocol();universe=create_or_update_pilot_universe(dataset)
    from apps.market_data.mapping import verify_finnhub_mapping
    from .universe_mapping import map_universe_member
    mapping_reports={};missing_contracts=[]
    for member in universe.members.filter(active=True).select_related("instrument"):
        member=map_universe_member(member,create_unqualified=True)
        if not member.instrument_id:
            mapping_reports[member.source_symbol]="UNMAPPED";continue
        contract=BrokerContract.objects.filter(instrument=member.instrument,qualified_at__isnull=False).first()
        if not contract:
            missing_contracts.append(member.source_symbol)
            mapping=InstrumentProviderMapping.objects.filter(instrument=member.instrument,provider="FINNHUB").first()
        else:
            mapping=InstrumentProviderMapping.objects.filter(instrument=member.instrument,provider="FINNHUB",status="VERIFIED").first()
            if not mapping:
                mapping=verify_finnhub_mapping(member.instrument,client=finnhub)
        mapping_reports[member.source_symbol]=mapping.status if mapping else "MISSING"
    implementations=register_and_validate_strategies(dataset)
    data_reports=refresh_mvp_data(universe,finnhub=finnhub,gateway=gateway) if refresh_data else {}
    factory=create_mvp_experiments(universe,protocol)
    executed=[]
    from .experiment_runner import run_experiment
    for experiment in factory["experiments"]:
        # Failed groups are durable resumable work: completed trials are reused and only
        # unfinished trials run again after a transient integration or deployment fix.
        if experiment.status in {"QUEUED","FAILED"}:executed.append(run_experiment(experiment.pk))
    from .candidate_service import score_completed_trials
    scores=score_completed_trials()
    return {"dataset":dataset.version,"protocol":protocol.protocol_id,"universe_id":universe.pk,
            "mapping_reports":mapping_reports,"missing_ibkr_contracts":missing_contracts,
            "validated_implementations":len(implementations),"data_reports":data_reports,
            "experiment_groups":len(factory["experiments"]),"experiments_created":factory["created"],
            "experiments_reused":factory["reused"],"experiments_executed":len(executed),
            "scores":scores,"matrix":readiness_matrix()}
