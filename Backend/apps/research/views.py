import json

from django.conf import settings
from django.db import transaction
from django.db.models import Count

from apps.core.throttling import throttle_response
from apps.core.views import response
from apps.portfolio_construction.models import PortfolioGoalAllocation

from .models import (
    GoalRecommendationPolicy,
    GoalRecommendationRun,
    InstrumentEligibilitySnapshot,
    ResearchCandidateScore,
    ResearchDatasetVersion,
    ResearchExperiment,
    ResearchStrategyDefinition,
    ResearchStrategyReadiness,
    ResearchUniverse,
)
from .services.acceptance import accept_recommendation, detach_recommendation
from .services.classification import hierarchy
from .services.recommendations import create_recommendation_run
from .services.mvp import mvp_status as build_mvp_status, readiness_matrix


def _actor(request):
    user = getattr(request, "user", None)
    return user.get_username() if user and user.is_authenticated else "operator/system"


def _payload(request):
    value = json.loads(request.body or b"{}")
    if not isinstance(value, dict):
        raise ValueError("Request body must be an object")
    return value


def _page(request, query, serializer):
    try:
        page = max(1, int(request.GET.get("page", 1)))
        page_size = max(1, min(100, int(request.GET.get("page_size", 50))))
    except ValueError as exc:
        raise ValueError("page and page_size must be integers") from exc
    count = query.count()
    start = (page - 1) * page_size
    items = [serializer(item) for item in query[start:start + page_size]]
    return response(items, meta={
        "count": count,
        "page": page,
        "page_size": page_size,
        "next_page": page + 1 if start + page_size < count else None,
        "previous_page": page - 1 if page > 1 else None,
    })


def dataset_versions(request):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    query = ResearchDatasetVersion.objects.order_by("-snapshot_date", "-pk")
    if request.GET.get("status"):
        query = query.filter(status=request.GET["status"].upper())
    return _page(request, query, lambda item: {
        "id": item.pk, "bundle_name": item.bundle_name, "version": item.version,
        "snapshot_date": item.snapshot_date, "status": item.status,
        "manifest_hash": item.manifest_hash, "validation_report": item.validation_report,
        "imported_at": item.imported_at, "activated_at": item.activated_at,
    })


def universes(request, universe_id=None, members=False):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    if members:
        try:
            universe = ResearchUniverse.objects.get(pk=universe_id)
        except ResearchUniverse.DoesNotExist:
            return response(status=404, error={"code": "NOT_FOUND", "message": "Universe not found", "details": {}})
        query = universe.members.select_related("issuer", "instrument").order_by("source_symbol")
        if request.GET.get("mapping_status"):
            query = query.filter(mapping_status=request.GET["mapping_status"].upper())
        return _page(request, query, lambda item: {
            "id": item.pk, "symbol": item.source_symbol, "security_name": item.security_name,
            "issuer_id": item.issuer_id, "cik": item.issuer.cik, "instrument_id": item.instrument_id,
            "currency": item.currency, "exchange_hint": item.exchange_hint,
            "membership_type": universe.membership_type, "membership_start": item.membership_start,
            "membership_end": item.membership_end, "mapping_status": item.mapping_status,
            "mapping_notes": item.mapping_notes, "active": item.active,
        })
    query = ResearchUniverse.objects.select_related("dataset_version").annotate(member_count=Count("members")).order_by("-dataset_version__snapshot_date")
    if request.GET.get("active") in {"true", "false"}:
        query = query.filter(active=request.GET["active"] == "true")
    return _page(request, query, lambda item: {
        "id": item.pk, "key": item.key, "name": item.name, "description": item.description,
        "dataset_version_id": item.dataset_version_id, "dataset_version": item.dataset_version.version,
        "membership_type": item.membership_type, "active": item.active,
        "member_count": item.member_count,
    })


def strategies(request, research_id=None):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    query = ResearchStrategyDefinition.objects.select_related("dataset_version").prefetch_related("implementations").order_by("research_id")
    if research_id:
        item = query.filter(research_id=research_id, dataset_version__status="ACTIVE").first()
        if not item:
            return response(status=404, error={"code": "NOT_FOUND", "message": "Research strategy not found", "details": {}})
        return response(_strategy_row(item, detail=True))
    for field in ("family", "scope", "role"):
        if request.GET.get(field):
            query = query.filter(**{field: request.GET[field] if field != "role" else request.GET[field].upper()})
    if request.GET.get("active") in {"true", "false"}:
        query = query.filter(active=request.GET["active"] == "true")
    return _page(request, query, _strategy_row)


def _strategy_row(item, detail=False):
    row = {
        "id": item.pk, "research_id": item.research_id, "name": item.name,
        "family": item.family, "scope": item.scope, "role": item.role,
        "production_status": item.production_status, "supported_directions": item.supported_directions,
        "supported_frequencies": item.supported_frequencies, "active": item.active,
        "dataset_version_id": item.dataset_version_id,
        "implementation_statuses": list(item.implementations.values_list("status", flat=True)),
    }
    if detail:
        row.update({
            "description": item.description, "research_hypothesis": item.research_hypothesis,
            "engine_compatibility": item.engine_compatibility, "required_data": item.required_data,
            "features": item.features, "signal_logic": item.signal_logic, "parameter_grid": item.parameter_grid,
            "eligibility_filters": item.eligibility_filters, "portfolio_construction": item.portfolio_construction,
            "risk_controls": item.risk_controls, "recommended_risk_levels": item.recommended_risk_levels,
            "recommended_goal_timeframes": item.recommended_goal_timeframes,
            "required_metrics": item.required_metrics, "known_failure_modes": item.known_failure_modes,
        })
    return row


def readiness(request):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    query = ResearchStrategyReadiness.objects.select_related("research_strategy").order_by("-as_of_date", "research_strategy__research_id")
    if request.GET.get("builder_ready") in {"true", "false"}:
        query = query.filter(builder_ready=request.GET["builder_ready"] == "true")
    return _page(request, query, lambda item: {
        "id": item.pk, "research_id": item.research_strategy.research_id, "as_of_date": item.as_of_date,
        "data_ready": item.data_ready, "features_ready": item.features_ready,
        "implementation_ready": item.implementation_ready, "backtest_ready": item.backtest_ready,
        "approved": item.approved, "builder_ready": item.builder_ready,
        "blocking_reasons": item.blocking_reasons,
    })


def candidate_scores(request):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    query = ResearchCandidateScore.objects.select_related("strategy", "instrument").order_by("-as_of_date", "-score")
    if request.GET.get("timeframe"):
        query = query.filter(goal_timeframe=request.GET["timeframe"].upper())
    if request.GET.get("risk_level"):
        query = query.filter(risk_level=request.GET["risk_level"])
    if request.GET.get("eligible") in {"true", "false"}:
        query = query.filter(eligible=request.GET["eligible"] == "true")
    return _page(request, query, lambda item: {
        "id": item.pk, "research_id": item.strategy.research_id,
        "instrument_id": item.instrument_id, "symbol": item.instrument.symbol if item.instrument else None,
        "goal_timeframe": item.goal_timeframe, "risk_level": item.risk_level,
        "as_of_date": item.as_of_date, "score": item.score, "eligible": item.eligible,
        "hard_rejection_reasons": item.hard_rejection_reasons, "expires_at": item.expires_at,
    })


def mvp_status(request,resource="status"):
    if request.method!="GET":
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"GET required","details":{}})
    try:
        if resource=="status":return response(build_mvp_status())
        matrix=readiness_matrix()
        if resource=="matrix":return response(matrix)
        if resource=="stocks":return response(matrix["stocks"])
        if resource=="strategies":
            rows=[]
            for key in matrix["strategy_keys"]:
                cells=[cell for stock in matrix["stocks"] for cell in stock["strategies"] if cell["strategy_key"]==key]
                rows.append({"strategy_key":key,"research_id":cells[0]["research_id"] if cells else None,
                             "validated_pairs":sum("NO_VALIDATED_IMPLEMENTATION" not in cell["blockers"] for cell in cells),
                             "completed_pairs":sum(cell["status"] in {"COMPLETED","BUILDER_READY"} for cell in cells),
                             "approved_pairs":sum(cell["approved"] for cell in cells),
                             "builder_ready":bool(cells and all(cell["builder_ready"] for cell in cells)),
                             "blockers":list(dict.fromkeys(code for cell in cells for code in cell["blockers"]))})
            return response(rows)
        raise ValueError("Unsupported MVP status resource")
    except ValueError as exc:
        return response(status=409,error={"code":"MVP_CONFIGURATION_INVALID","message":str(exc),"details":{}})


def experiments(request, experiment_id):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    try:
        item = ResearchExperiment.objects.select_related("strategy", "universe", "protocol").get(pk=experiment_id)
    except ResearchExperiment.DoesNotExist:
        return response(status=404, error={"code": "NOT_FOUND", "message": "Experiment not found", "details": {}})
    return response({
        "id": item.pk, "research_id": item.strategy.research_id, "universe_id": item.universe_id,
        "protocol_id": item.protocol.protocol_id, "experiment_type": item.experiment_type,
        "parameter_budget": item.parameter_budget, "status": item.status, "error": item.error,
        "trial_count": item.trials.count(), "started_at": item.started_at, "completed_at": item.completed_at,
    })


def goal_recommendations(request, goal_id):
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    key = request.headers.get("Idempotency-Key")
    if not key:
        return response(status=400, error={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key header is required", "details": {}})
    throttled = throttle_response(
        request, "research_recommendation", limit=settings.OPTIMIZATION_THROTTLE_LIMIT,
        window_seconds=settings.EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS,
    )
    if throttled:
        return throttled
    try:
        payload = _payload(request)
        unknown = set(payload) - {"policy_id"}
        if unknown:
            raise ValueError(f"Unsupported recommendation fields: {', '.join(sorted(unknown))}")
        goal = PortfolioGoalAllocation.objects.select_related("plan").get(pk=goal_id)
        policy = GoalRecommendationPolicy.objects.get(pk=payload["policy_id"], active=True) if payload.get("policy_id") else None
        run = create_recommendation_run(goal, key, policy=policy, defer=True)
        from .tasks import generate_recommendation
        transaction.on_commit(lambda: generate_recommendation.delay(run.pk))
        return response(_recommendation_row(run, detail=True), status=202)
    except (ValueError, json.JSONDecodeError, PortfolioGoalAllocation.DoesNotExist, GoalRecommendationPolicy.DoesNotExist) as exc:
        return response(status=400, error={"code": "RECOMMENDATION_FAILED", "message": str(exc), "details": {}})


def recommendation_detail(request, run_id, action=None):
    if action is None and request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    if action == "accept" and request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    try:
        run = GoalRecommendationRun.objects.select_related("goal_allocation", "policy", "dataset_version", "protocol_version").get(pk=run_id)
        if action == "accept":
            acceptance, created = accept_recommendation(run, actor=_actor(request))
            run.refresh_from_db()
            return response({"created": created, "acceptance_id": acceptance.pk, "recommendation": _recommendation_row(run, detail=True)})
        return response(_recommendation_row(run, detail=True))
    except GoalRecommendationRun.DoesNotExist:
        return response(status=404, error={"code": "NOT_FOUND", "message": "Recommendation not found", "details": {}})
    except ValueError as exc:
        return response(status=409, error={"code": "RECOMMENDATION_CONFLICT", "message": str(exc), "details": {}})


def detach_goal_recommendation(request, goal_id):
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    try:
        goal = detach_recommendation(goal_id, actor=_actor(request))
        return response({"goal_id": goal.pk, "construction_source": goal.construction_source, "accepted_recommendation_run_id": None})
    except PortfolioGoalAllocation.DoesNotExist:
        return response(status=404, error={"code": "NOT_FOUND", "message": "Goal not found", "details": {}})


def _recommendation_row(run, detail=False):
    row = {
        "id": run.pk, "goal_id": run.goal_allocation_id, "requested_plan_version": run.requested_plan_version,
        "status": run.status, "as_of_date": run.as_of_date, "metrics": run.metrics,
        "warnings": run.warnings, "error": run.error, "expires_at": run.expires_at,
        "accepted_at": run.accepted_at, "dataset_version_id": run.dataset_version_id,
        "protocol_version_id": run.protocol_version_id, "created_at": run.created_at,
        "blockers": run.warnings if run.status == "BLOCKED" else [],
    }
    if detail:
        rows=[]
        for sleeve in run.sleeves.select_related(
            "instrument", "research_strategy", "execution_strategy_definition", "universe_member"
        ).order_by("rank"):
            eligibility=sleeve.universe_member.eligibility_snapshots.filter(as_of_date__lte=run.as_of_date).order_by("-as_of_date").first()
            rows.append({
            "id": sleeve.pk, "instrument_id": sleeve.instrument_id, "symbol": sleeve.instrument.symbol,
            "gics": hierarchy(sleeve.instrument.classifications.filter(
                taxonomy_version=run.dataset_version, effective_from__lte=run.as_of_date
            ).select_related("sub_industry_node__parent__parent__parent").order_by("-effective_from").first()),
            "research_id": sleeve.research_strategy.research_id,
            "strategy_name": sleeve.research_strategy.name,
            "strategy_family": sleeve.research_strategy.family,
            "execution_strategy_definition_id": sleeve.execution_strategy_definition_id,
            "execution_timeframe": sleeve.execution_timeframe, "parameters": sleeve.parameters,
            "sleeve_weight": sleeve.sleeve_weight, "stock_weight": sleeve.stock_weight,
            "strategy_share": sleeve.strategy_share, "candidate_score": sleeve.candidate_score,
            "expected_return": sleeve.expected_return, "expected_volatility": sleeve.expected_volatility,
            "expected_drawdown": sleeve.expected_drawdown, "cost_metrics": sleeve.cost_metrics,
            "rationale": sleeve.rationale, "rank": sleeve.rank,
            "data_source":(eligibility.metrics or {}).get("provider") if eligibility else None,
            "latest_data_date":(eligibility.metrics or {}).get("latest_data_date") if eligibility else None,
        })
        row["sleeves"]=rows
    return row
