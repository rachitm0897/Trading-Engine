from datetime import timedelta
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.db.models import Count
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.allocation.models import RebalanceRun
from apps.instruments.models import BrokerContract, InstrumentProviderMapping
from apps.portfolio_construction.models import PortfolioConstructionPlan, PortfolioGoalAllocation
from apps.portfolios.models import TradingPortfolio
from apps.research.engines.base import ResearchProtocolContext
from apps.research.engines.single_asset import SingleAssetBacktestEngine
from apps.research.implementations.wave0 import implementation_for
from apps.research.models import ResearchCorporateAction, ResearchDailyBar, ResearchExperiment, ResearchTrial
from apps.research.services.acceptance import accept_recommendation
from apps.research.services.bundle_import import import_bundle
from apps.research.services.candidate_service import score_completed_trials
from apps.research.services.eligibility import calculate_member_eligibility
from apps.research.services.experiment_runner import run_experiment
from apps.research.services.experiments import subperiod_consistency
from apps.research.services.mvp import (
    EXPECTED_STOCKS,
    EXPECTED_STRATEGIES,
    STRATEGY_SPECS,
    create_mvp_experiments,
    create_or_update_pilot_universe,
    mvp_settings,
    register_and_validate_strategies,
)
from apps.research.services.recommendations import create_recommendation_run, run_recommendation
from apps.research.services.research_data import store_research_history, validate_research_history
from apps.strategies.models import StrategyInstance


pytestmark=pytest.mark.django_db
BUNDLE=Path(__file__).resolve().parents[2]/"Trading_Engine_Stock_Strategy_Universe_JSON"
D=Decimal


def _weekdays(count):
    result=[];cursor=timezone.localdate()
    while len(result)<count:
        if cursor.weekday()<5:result.append(cursor)
        cursor-=timedelta(days=1)
    return list(reversed(result))


def _prepare_ready_pilot():
    dataset,_=import_bundle(BUNDLE,activate=True)
    universe=create_or_update_pilot_universe(dataset)
    implementations=register_and_validate_strategies(dataset)
    dates=_weekdays(800);now=timezone.now();bars=[]
    for stock_index,member in enumerate(universe.members.filter(active=True).select_related("instrument").order_by("source_symbol")):
        InstrumentProviderMapping.objects.update_or_create(
            instrument=member.instrument,provider="FINNHUB",
            defaults={"provider_symbol":member.source_symbol,"currency":"USD","status":"VERIFIED",
                      "verification_method":"MANUAL","verified_at":now},
        )
        BrokerContract.objects.create(instrument=member.instrument,conid=9_000_000+stock_index,
                                      local_symbol=member.source_symbol,primary_exchange="NYSE",qualified_at=now)
        for index,trading_date in enumerate(dates):
            close=D("80")+D(stock_index*10)+D(index)/D("10")
            bars.append(ResearchDailyBar(
                instrument=member.instrument,trading_date=trading_date,
                raw_open=close,raw_high=close+D(1),raw_low=close-D(1),raw_close=close,
                adjusted_open=close,adjusted_high=close+D(1),adjusted_low=close-D(1),adjusted_close=close,
                total_return_close=close,volume=1_000_000,cash_dividend=0,split_factor=1,adjustment_factor=1,
                provider="FINNHUB",provider_timestamp=now,revision_timestamp=now,data_version=1,quality_status="VALID",
            ))
    ResearchDailyBar.objects.bulk_create(bars)
    for member in universe.members.filter(active=True):calculate_member_eligibility(member)
    return dataset,universe,implementations


def test_mvp_configuration_and_semantic_registry_are_exact(settings):
    assert settings.ALLOW_LIVE_TRADING is False
    settings.RESEARCH_MVP_STOCKS=",".join(EXPECTED_STOCKS)
    settings.RESEARCH_MVP_STRATEGIES=",".join(EXPECTED_STRATEGIES)
    config=mvp_settings()
    assert config.stocks==EXPECTED_STOCKS and config.strategies==EXPECTED_STRATEGIES
    dataset,_=import_bundle(BUNDLE,activate=True)
    universe=create_or_update_pilot_universe(dataset)
    rows=register_and_validate_strategies(dataset)
    assert set(universe.members.filter(active=True).values_list("source_symbol",flat=True))==set(EXPECTED_STOCKS)
    assert {row.executable_strategy_definition.key for row in rows}==set(EXPECTED_STRATEGIES)
    assert all(row.status=="VALIDATED" and row.exact_semantic_match for row in rows)
    assert all(row.approval_record["semantic_validation"]["runtime_plugin_parity"] for row in rows)


def test_all_five_wave0_strategies_are_deterministic_next_bar_and_long_only():
    bars=[{"open":100+index/10,"high":101+index/10,"low":99+index/10,
           "close":100+index/10+((index%17)-8)/10,"volume":1_000_000} for index in range(320)]
    for key in EXPECTED_STRATEGIES:
        parameters=STRATEGY_SPECS[key]["defaults"]
        strategy=implementation_for(key)
        first=strategy.signals(bars,parameters,ResearchProtocolContext())
        second=strategy.signals(bars,parameters,ResearchProtocolContext())
        assert first.desired_exposure==second.desired_exposure
        assert all(0<=value<=1 for value in first.desired_exposure)
        result=SingleAssetBacktestEngine().run(strategy,bars,parameters,ResearchProtocolContext())
        assert result.positions[0]==0 and result.diagnostics["execution"]=="NEXT_OPEN"


def test_zero_return_subperiod_metrics_are_strict_json():
    result=subperiod_consistency([0.0,0.0,0.0])
    assert result["coefficient_of_variation"] is None
    json.dumps(result,allow_nan=False)


def test_research_data_versions_splits_dividends_and_quality_are_reconciled():
    dataset,_=import_bundle(BUNDLE,activate=True)
    member=dataset.universes.first().members.first();instrument=member.instrument;now=timezone.now()
    InstrumentProviderMapping.objects.update_or_create(
        instrument=instrument,provider="FINNHUB",
        defaults={"provider_symbol":instrument.symbol,"status":"VERIFIED","verified_at":now},
    )
    dates=_weekdays(4)
    raw=[{"trading_date":day,"open":100,"high":102,"low":99,"close":101,"volume":1000} for day in dates]
    actions=[
        {"action_type":"DIVIDEND","effective_date":dates[1],"payload":{"amount":"0.25"}},
        {"action_type":"SPLIT","effective_date":dates[2],"payload":{"factor":"2"}},
    ]
    assert store_research_history(instrument,raw,actions,provider="FINNHUB")==4
    assert store_research_history(instrument,raw,actions,provider="FINNHUB")==0
    report=validate_research_history(instrument,minimum_bars=4)
    assert report["status"]=="VALID" and report["valid_bar_count"]==4
    assert report["latest_date"]==dates[-1].isoformat()
    assert ResearchCorporateAction.objects.filter(instrument=instrument,quality_status="VALID").count()==2
    assert ResearchDailyBar.objects.filter(instrument=instrument).count()==4


def test_factory_creates_exactly_25_idempotent_groups_and_fixed_baseline_can_recommend():
    dataset,universe,implementations=_prepare_ready_pilot()
    first=create_mvp_experiments(universe,dataset.protocols.get(active=True))
    second=create_mvp_experiments(universe,dataset.protocols.get(active=True))
    assert len(first["experiments"])==25 and first["created"]==25
    assert len(second["experiments"])==25 and second["created"]==0 and second["reused"]==25
    assert ResearchExperiment.objects.filter(experiment_type="MVP_WALK_FORWARD").count()==25
    assert ResearchTrial.objects.count()==5*(1+6+8+6+8)
    fixed=next(row for row in implementations if row.executable_strategy_definition.key=="FIXED_WEIGHT_REBALANCE")
    fixed.approval_record={**fixed.approval_record,"shadow_validated":True};fixed.save(update_fields=["approval_record"])
    fixed_experiments=ResearchExperiment.objects.filter(strategy=fixed.research_strategy,status="QUEUED")
    for experiment in fixed_experiments:run_experiment(experiment.pk)
    scored=score_completed_trials()
    fixed.refresh_from_db()
    assert scored["candidate_scores_updated"]>0 and fixed.status=="BUILDER_READY"
    account=BrokerAccount.objects.create(account_id="DU-MVP",net_liquidation=100_000,available_cash=100_000)
    portfolio=TradingPortfolio.objects.create(name="MVP",account=account)
    plan=PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    goal=PortfolioGoalAllocation.objects.create(plan=plan,name="Hurry",allocation_weight=1,
                                                 timeframe_bucket="HURRY",risk_level=1)
    run=create_recommendation_run(goal,"mvp-recommendation",defer=False)
    run=run_recommendation(run)
    assert run.status=="COMPLETED" and 1<=run.sleeves.count()<=5
    assert run.sleeves.values("instrument_id").annotate(count=Count("id")).filter(count__gt=1).count()==0
    acceptance,created=accept_recommendation(run,actor="test")
    assert created and acceptance.change_summary["created_strategy_instances"]==0
    assert StrategyInstance.objects.count()==0 and RebalanceRun.objects.count()==0


def test_non_now_zero_candidates_is_blocked_with_precise_reasons():
    dataset,_=import_bundle(BUNDLE,activate=True)
    create_or_update_pilot_universe(dataset);register_and_validate_strategies(dataset)
    account=BrokerAccount.objects.create(account_id="DU-BLOCK",net_liquidation=10_000,available_cash=10_000)
    portfolio=TradingPortfolio.objects.create(name="Blocked",account=account)
    plan=PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    goal=PortfolioGoalAllocation.objects.create(plan=plan,name="Build",allocation_weight=1,
                                                 timeframe_bucket="BUILD",risk_level=3)
    run=run_recommendation(create_recommendation_run(goal,"blocked",defer=False))
    assert run.status=="BLOCKED" and run.sleeves.count()==0
    assert "NO_APPROVED_CANDIDATES" not in {item["code"] for item in run.warnings}
    assert {item["code"] for item in run.warnings}&{
        "FINNHUB_MAPPING_MISSING","IBKR_CONTRACT_NOT_QUALIFIED","INSUFFICIENT_VALID_HISTORY",
        "NO_PASSING_BACKTEST","STRATEGY_NOT_BUILDER_READY",
    }
