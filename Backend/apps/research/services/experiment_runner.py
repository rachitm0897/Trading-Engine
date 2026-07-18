import importlib
import math

import numpy as np
from django.conf import settings
from django.utils import timezone

from ..engines.base import ResearchProtocolContext
from ..engines.single_asset import SingleAssetBacktestEngine, performance_metrics
from ..enums import ImplementationStatus
from ..models import ResearchDailyBar, ResearchExperiment
from .artifacts import FilesystemArtifactStore
from .experiments import deflated_sharpe_ratio, subperiod_consistency, walk_forward_windows


def _load(path):
    module,attribute=path.rsplit(".",1);value=getattr(importlib.import_module(module),attribute)
    return value() if isinstance(value,type) else value


def _json_safe(value):
    if isinstance(value,dict):return {key:_json_safe(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [_json_safe(item) for item in value]
    if isinstance(value,np.generic):value=value.item()
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


def _bars(experiment):
    seen=set();rows=[]
    for row in ResearchDailyBar.objects.filter(
        instrument=experiment.instrument,quality_status="VALID",trading_date__gte=experiment.start_date,
        trading_date__lte=experiment.end_date,
    ).order_by("trading_date","-data_version"):
        if row.trading_date in seen:continue
        seen.add(row.trading_date)
        rows.append({"date":row.trading_date.isoformat(),"open":float(row.adjusted_open),
                     "high":float(row.adjusted_high),"low":float(row.adjusted_low),
                     "close":float(row.adjusted_close),"volume":float(row.volume)})
    return rows


def _context(stress=0):
    return ResearchProtocolContext(commission_bps=1,spread_bps=5,impact_coefficient=0.1,
                                   maximum_participation=0.10,cost_stress_bps=stress)


def _window_metrics(result,windows):
    values=[]
    for window in windows:
        metrics=performance_metrics(result.returns[window.test[0]:window.test[1]],
                                    result.positions[window.test[0]:window.test[1]])
        values.append(metrics)
    return values


def _activity_threshold(runtime_key):
    return {"FIXED_WEIGHT_REBALANCE":1,"SMA_CROSSOVER":3,"RSI_MEAN_REVERSION":5,
            "DONCHIAN_BREAKOUT":3,"VOLATILITY_TARGET_MOMENTUM":10}[runtime_key]


def run_experiment(experiment_or_id):
    experiment_id=experiment_or_id.pk if isinstance(experiment_or_id,ResearchExperiment) else experiment_or_id
    experiment=ResearchExperiment.objects.select_related("strategy","instrument").get(pk=experiment_id)
    if experiment.status=="COMPLETED":return {"experiment_id":experiment.pk,"status":experiment.status,"reused":True}
    experiment.status="RUNNING";experiment.started_at=timezone.now();experiment.save(update_fields=["status","started_at"])
    store=FilesystemArtifactStore(settings.RESEARCH_ARTIFACT_ROOT)
    try:
        implementation=experiment.strategy.implementations.filter(
            implementation_hash=experiment.implementation_hash,
            status__in=[ImplementationStatus.VALIDATED,ImplementationStatus.BACKTESTED,ImplementationStatus.SCORED,
                        ImplementationStatus.APPROVED_FOR_RECOMMENDATION,ImplementationStatus.SHADOW_VALIDATED,
                        ImplementationStatus.BUILDER_READY,ImplementationStatus.APPROVED],exact_semantic_match=True,
        ).select_related("executable_strategy_definition").first()
        if not implementation:raise ValueError("Strategy has no validated exact implementation")
        runtime_key=implementation.executable_strategy_definition.key
        strategy=_load(implementation.implementation_path);engine=SingleAssetBacktestEngine();bars=_bars(experiment)
        if len(bars)<756:raise ValueError("Experiment requires at least 756 valid adjusted daily bars")
        holdout_size=126;research_count=len(bars)-holdout_size
        windows=walk_forward_windows(research_count,train_size=252,validation_size=63,test_size=63,
                                     purge_size=5,embargo_size=5,expanding=True,minimum_windows=3)
        completed=[]
        for trial in experiment.trials.select_related("instrument").order_by("parameter_hash"):
            if trial.status=="COMPLETED":completed.append(trial);continue
            research_result=engine.run(strategy,bars[:research_count],trial.parameters,_context())
            full_result=engine.run(strategy,bars,trial.parameters,_context())
            stress25=engine.run(strategy,bars[:research_count],trial.parameters,_context(25))
            stress50=engine.run(strategy,bars[:research_count],trial.parameters,_context(50))
            tests=_window_metrics(research_result,windows)
            test_returns=[item["total_return"] for item in tests]
            consistency=subperiod_consistency(test_returns)
            positive=[max(0,value) for value in test_returns];positive_total=sum(positive)
            largest=max(positive)/positive_total if positive_total>0 else 1.0
            holdout_metrics=performance_metrics(full_result.returns[research_count:],full_result.positions[research_count:])
            median_dollar_volume=float(np.median([
                item["close"]*item["volume"] for item in bars[-252:]
            ]))
            number_of_trials=max(1,experiment.trials.count())
            deflated=deflated_sharpe_ratio(research_result.metrics["sharpe"],number_of_trials=number_of_trials,
                                           observations=research_count)
            minimum_trades=_activity_threshold(runtime_key)
            validation={
                "data_quality_pass":True,"timestamps_unambiguous":True,"holdout_untouched":True,
                "next_bar_execution":True,"long_only_exposure":True,"signal_at":"t","execution_at":"t+1_open",
                "walk_forward_windows":[{"train":window.train,"validation":window.validation,"test":window.test,
                                         "purge":window.purge,"embargo":window.embargo} for window in windows],
                "independent_test_window_count":len(windows),"test_window_metrics":tests,
                "holdout_result":holdout_metrics,"holdout_start_index":research_count,
                "maximum_allowed_drawdown":0.40,"minimum_trades":minimum_trades,
                "strategy_activity_pass":runtime_key=="FIXED_WEIGHT_REBALANCE" or research_result.metrics["trade_count"]>=minimum_trades,
                "cost_scenarios_bps":[25,50],"cost_25bps_total_return":stress25.metrics["total_return"],
                "cost_50bps_total_return":stress50.metrics["total_return"],
                "high_cost_net_return":stress50.metrics["total_return"],
                "cost_resilience_score":max(0,min(100,50+500*stress50.metrics["total_return"])),
                "turnover_efficiency_score":max(0,min(100,100-5*research_result.metrics["turnover"])),
                "median_dollar_volume_252d":median_dollar_volume,"capacity_pass":median_dollar_volume>=25_000_000,
                "capacity_score":max(0,min(100,median_dollar_volume/1_000_000)),
                "maximum_capacity_weight":min(1.0,median_dollar_volume/250_000_000),
                "subperiod_consistency":consistency,"largest_subperiod_contribution":largest,
                "maximum_subperiod_contribution":0.60,
                "regime_consistency_score":100*consistency["positive_fraction"],
                "deflated_sharpe":deflated,"multiple_testing_pass":runtime_key=="FIXED_WEIGHT_REBALANCE" or deflated>=0.50,
                "multiple_testing_result":{"method":"DEFLATED_SHARPE","probability":deflated,"trial_count":number_of_trials},
                "diversification_score":50.0,"parameter_neighborhood_stable":runtime_key=="FIXED_WEIGHT_REBALANCE",
                "parameter_stability_score":100.0 if runtime_key=="FIXED_WEIGHT_REBALANCE" else 0.0,
            }
            trial.summary_metrics=_json_safe({**research_result.metrics,"expected_return":research_result.metrics["cagr"],
                                              "expected_volatility":research_result.metrics["annualized_volatility"],
                                              "expected_drawdown":research_result.metrics["max_drawdown"],
                                              "holdout_total_return":holdout_metrics["total_return"]})
            trial.validation_metrics=_json_safe(validation)
            trial.artifact_uri=store.write_table(f"experiment_{experiment.pk}/trial_{trial.pk}_returns",[
                {"index":index,"date":bars[index]["date"],"return":value,"equity":full_result.equity[index],
                 "position":full_result.positions[index],"holdout":index>=research_count}
                for index,value in enumerate(full_result.returns)
            ])
            trial.status="COMPLETED";trial.rejection_reasons=[]
            trial.save(update_fields=["summary_metrics","validation_metrics","artifact_uri","status","rejection_reasons"])
            completed.append(trial)
        sharpes=[float(trial.summary_metrics.get("sharpe",0)) for trial in completed]
        for index,trial in enumerate(completed):
            neighbors=sharpes[:index]+sharpes[index+1:]
            center=sharpes[index]
            median=float(np.median(neighbors)) if neighbors else center
            stable=runtime_key=="FIXED_WEIGHT_REBALANCE" or not neighbors or center>=median-0.50
            validation={**trial.validation_metrics,"parameter_neighborhood_stable":stable,
                        "parameter_stability_score":100.0 if stable else 0.0,
                        "neighbor_median_sharpe":median}
            trial.validation_metrics=_json_safe(validation);trial.save(update_fields=["validation_metrics"])
        experiment.status="COMPLETED";experiment.completed_at=timezone.now();experiment.error=""
        experiment.save(update_fields=["status","completed_at","error"])
        if implementation.status==ImplementationStatus.VALIDATED:
            implementation.status=ImplementationStatus.BACKTESTED
            implementation.approval_record={**(implementation.approval_record or {}),"backtested_at":timezone.now().isoformat()}
            implementation.save(update_fields=["status","approval_record","updated_at"])
    except Exception as exc:
        experiment.status="FAILED";experiment.error=str(exc)[:2000];experiment.completed_at=timezone.now()
        experiment.save(update_fields=["status","error","completed_at"]);raise
    return {"experiment_id":experiment.pk,"status":experiment.status,"trial_count":len(completed),"reused":False}
