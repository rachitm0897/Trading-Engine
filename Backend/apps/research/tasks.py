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
