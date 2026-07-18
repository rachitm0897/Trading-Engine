from celery import shared_task
from django.conf import settings


@shared_task
def refresh_research_pipeline():
    if not settings.RESEARCH_ENABLED:
        return {"status": "DISABLED"}
    from .models import ResearchUniverse
    from .services.eligibility import calculate_universe_eligibility

    result = {}
    for universe in ResearchUniverse.objects.filter(active=True):
        result[str(universe.pk)] = calculate_universe_eligibility(universe)
    return result


@shared_task
def calculate_features():
    if not settings.RESEARCH_ENABLED:
        return {"status": "DISABLED"}
    from .models import ResearchFeatureDefinition
    from .services.features import FEATURE_REGISTRY

    updated = ResearchFeatureDefinition.objects.filter(
        key__in=FEATURE_REGISTRY, status="DECLARED"
    ).update(
        status="IMPLEMENTED",
        batch_implementation_path="apps.research.services.features.calculate_feature",
        implementation_version="1",
    )
    return {"implemented_features": updated, "note": "VALIDATED requires deterministic golden-vector evidence"}


@shared_task
def run_experiment(experiment_id):
    if not settings.RESEARCH_ENABLED:
        return {"status": "DISABLED"}
    from .services.experiment_runner import run_experiment as execute
    return execute(experiment_id)


@shared_task
def score_current_candidates():
    if not settings.RESEARCH_ENABLED:
        return {"status": "DISABLED"}
    from .services.candidate_service import score_completed_trials
    return score_completed_trials()


@shared_task
def generate_recommendation(run_id):
    from .services.recommendations import run_recommendation
    run = run_recommendation(run_id)
    return {"recommendation_run_id": run.pk, "status": run.status}


@shared_task
def run_recommendation_mvp_pipeline():
    if not settings.RESEARCH_ENABLED or not settings.RESEARCH_MVP_ENABLED:
        return {"status":"DISABLED"}
    from .services.mvp import run_mvp_pipeline
    try:
        import redis
        client=redis.Redis.from_url(settings.CELERY_BROKER_URL)
        client.ping()
        lock=client.lock("research:recommendation-mvp:pipeline",timeout=60*60*3,blocking_timeout=0)
        if not lock.acquire(blocking=False):return {"status":"LOCKED"}
    except Exception as exc:
        return {"status":"LOCK_UNAVAILABLE","error":str(exc)[:500]}
    try:
        result=run_mvp_pipeline()
        from django.core.cache import cache
        from .services.mvp import mvp_status
        cache.set("research:recommendation-mvp:status",mvp_status(),timeout=300)
        from .models import ResearchCandidateScore
        from apps.portfolio_construction.rules import MAXIMUM_RISK
        from django.utils import timezone
        for timeframe,maximum_risk in MAXIMUM_RISK.items():
            if timeframe=="NOW":continue
            for risk_level in range(1,maximum_risk+1):
                ids=list(ResearchCandidateScore.objects.filter(
                    goal_timeframe=timeframe,risk_level=risk_level,eligible=True,
                    expires_at__gt=timezone.now(),instrument__symbol__in=["AAPL","JPM","XOM","JNJ","WMT"],
                ).order_by("-score").values_list("pk",flat=True)[:25])
                cache.set(f"research:recommendation-mvp:candidates:{timeframe}:{risk_level}",ids,timeout=300)
        return {"status":"COMPLETED","experiment_groups":result["experiment_groups"],
                "experiments_executed":result["experiments_executed"],"scores":result["scores"]}
    finally:
        if lock:
            try:lock.release()
            except Exception:pass
