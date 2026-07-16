from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import ResearchCandidateScore, ResearchTrial
from .scoring import candidate_score


def _clamp(value):
    return max(0.0, min(100.0, float(value)))


def _components(trial):
    summary = trial.summary_metrics or {}
    validation = trial.validation_metrics or {}
    return {
        "out_of_sample_sharpe": _clamp(50 + 20 * float(summary.get("sharpe", 0))),
        "calmar": _clamp(50 + 15 * float(summary.get("calmar", 0))),
        "drawdown_fit": _clamp(100 * (1 - float(summary.get("max_drawdown", 1)) / max(float(validation.get("maximum_allowed_drawdown", 0.30)), 1e-9))),
        "regime_consistency": _clamp(validation.get("regime_consistency_score", 0)),
        "parameter_stability": _clamp(validation.get("parameter_stability_score", 0)),
        "cost_resilience": _clamp(validation.get("cost_resilience_score", 0)),
        "turnover_efficiency": _clamp(validation.get("turnover_efficiency_score", 0)),
        "capacity": _clamp(validation.get("capacity_score", 0)),
        "diversification_contribution": _clamp(validation.get("diversification_score", 0)),
    }


def score_completed_trials():
    created = 0
    for trial in ResearchTrial.objects.filter(status="COMPLETED", instrument__isnull=False).select_related(
        "experiment__strategy", "experiment__dataset_version", "experiment__protocol"
    ):
        validation = trial.validation_metrics or {}
        metrics = {
            "data_quality_pass": validation.get("data_quality_pass", False),
            "timestamps_unambiguous": validation.get("timestamps_unambiguous", False),
            "high_cost_net_return": validation.get("high_cost_net_return", -1),
            "maximum_drawdown": trial.summary_metrics.get("max_drawdown", 1),
            "maximum_allowed_drawdown": validation.get("maximum_allowed_drawdown", 0.30),
            "trade_count": trial.summary_metrics.get("trade_count", 0),
            "minimum_trades": validation.get("minimum_trades", 20),
            "parameter_neighborhood_stable": validation.get("parameter_neighborhood_stable", False),
            "capacity_pass": validation.get("capacity_pass", False),
            "largest_subperiod_contribution": validation.get("largest_subperiod_contribution", 1),
            "maximum_subperiod_contribution": 0.60,
            "multiple_testing_pass": validation.get("multiple_testing_pass", False),
            "holdout_untouched": validation.get("holdout_untouched", False),
        }
        result = candidate_score(_components(trial), metrics)
        strategy = trial.experiment.strategy
        for timeframe in strategy.recommended_goal_timeframes:
            for risk_level in strategy.recommended_risk_levels:
                ResearchCandidateScore.objects.update_or_create(
                    strategy=strategy,
                    instrument=trial.instrument,
                    goal_timeframe=timeframe,
                    risk_level=risk_level,
                    as_of_date=timezone.localdate(),
                    defaults={
                        "candidate_type": strategy.role,
                        "score": result["score"],
                        "eligible": result["eligible"],
                        "hard_rejection_reasons": result["hard_rejection_reasons"],
                        "best_parameters": trial.parameters,
                        "metrics": trial.summary_metrics,
                        "regime_metrics": {"consistency": validation.get("regime_consistency_score", 0)},
                        "cost_metrics": {"high_cost_net_return": validation.get("high_cost_net_return")},
                        "stability_metrics": {"stable": validation.get("parameter_neighborhood_stable", False)},
                        "capacity_metrics": {"pass": validation.get("capacity_pass", False)},
                        "protocol_version": trial.experiment.protocol,
                        "dataset_version": trial.experiment.dataset_version,
                        "expires_at": timezone.now() + timedelta(days=settings.RESEARCH_SCORE_MAX_AGE_DAYS),
                    },
                )
                created += 1
    return {"candidate_scores_updated": created}
