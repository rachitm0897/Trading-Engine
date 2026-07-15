from django.conf import settings
from django.urls import path
from apps.core import views
from apps.event_bus import views as streaming_views
from apps.allocation import views as allocation_views
from apps.rebalancing import views as rebalancing_views
from apps.position_sizing import views as sizing_views
from apps.strategies import views as strategy_views
from apps.core import analytics as analytics_views
from apps.market_data import views as market_data_views
from apps.portfolio_optimization import views as optimization_views
from apps.portfolio_construction import views as construction_views

api_patterns = [
    path("system/", views.system), path("auth/session/",views.auth_session), path("gateway/", views.gateway), path("accounts/", views.accounts),
    path("instruments/", views.instruments), path("portfolios/", views.portfolios), path("positions/", views.positions),
    path("rebalances/", views.rebalances),
    path("orders/", views.orders), path("orders/<str:internal_id>/detail/", views.orders, {"action":"detail"}), path("orders/<str:internal_id>/", views.orders), path("orders/<str:internal_id>/cancel/", views.orders, {"action":"cancel"}), path("executions/", views.executions), path("reconciliation/", views.reconciliation),
    path("risk/", views.risk), path("audit/", views.audit),
]
urlpatterns = [path("healthz", views.health),path("metrics",streaming_views.prometheus_metrics)] + [path(f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
new_api = [
    path("dashboard/summary/",analytics_views.dashboard_summary),path("portfolios/series/",analytics_views.portfolio_series),
    path("strategy-definitions/",strategy_views.definitions),path("strategy-definitions/<str:key>/",strategy_views.definitions),
    path("strategy-instances/",strategy_views.instances),path("strategy-instances/<int:instance_id>/",strategy_views.instances),
    path("strategy-instances/<int:instance_id>/enable/",strategy_views.action,{"action_name":"enable"}),
    path("strategy-instances/<int:instance_id>/pause/",strategy_views.action,{"action_name":"pause"}),
    path("strategy-instances/<int:instance_id>/evaluate/",strategy_views.action,{"action_name":"evaluate"}),
    path("strategy-instances/<int:instance_id>/flatten/",strategy_views.action,{"action_name":"flatten"}),
    path("strategy-instances/<int:instance_id>/state/",strategy_views.related,{"resource":"state"}),
    path("strategy-instances/<int:instance_id>/signals/",strategy_views.related,{"resource":"signals"}),
    path("strategy-instances/<int:instance_id>/runs/",strategy_views.related,{"resource":"runs"}),
    path("strategy-instances/<int:instance_id>/targets/",strategy_views.related,{"resource":"targets"}),
    path("strategy-instances/<int:instance_id>/execution-timeline/",strategy_views.related,{"resource":"execution-timeline"}),
    path("strategy-instances/<int:instance_id>/chart/",strategy_views.chart),
    path("strategy-policies/",strategy_views.policies),path("instruments/search/",strategy_views.search_instruments),path("instruments/resolve/",strategy_views.resolve),
    path("streaming/health/",streaming_views.health),path("streaming/topics/",streaming_views.topics),
    path("streaming/consumer-lag/",streaming_views.consumer_lag),path("streaming/dead-letter/",streaming_views.dead_letter),
    path("streaming/replay/",streaming_views.replay),path("streaming/replay/<int:replay_id>/",streaming_views.replay_status),
    path("allocations/policies/",allocation_views.policies),path("allocations/flows/",allocation_views.flows),
    path("allocations/runs/",allocation_views.runs),path("allocations/runs/<int:run_id>/",allocation_views.runs),
    path("rebalancing/policies/",rebalancing_views.policies),path("rebalancing/preview/",rebalancing_views.execute,{"preview":True}),
    path("rebalancing/run/",rebalancing_views.execute,{"preview":False}),path("rebalancing/runs/",rebalancing_views.runs),
    path("rebalancing/runs/<int:run_id>/",rebalancing_views.runs),path("position-sizing/preview/",sizing_views.preview),
    path("position-sizing/decisions/<int:decision_id>/",sizing_views.decision),
    path("data-providers/finnhub/",market_data_views.status),
    path("data-providers/finnhub/configure/",market_data_views.configure),
    path("data-providers/finnhub/test/",market_data_views.test),
    path("portfolio-universe/",optimization_views.universes),
    path("portfolio-optimization/policies/",optimization_views.policies),
    path("portfolio-optimization/preview/",optimization_views.execute,{"preview":True}),
    path("portfolio-optimization/run/",optimization_views.execute,{"preview":False}),
    path("portfolio-optimization/runs/",optimization_views.runs),
    path("portfolio-optimization/runs/<int:run_id>/",optimization_views.runs),
    path("portfolio-construction/plans/",construction_views.plans),
    path("portfolio-construction/plans/<int:plan_id>/",construction_views.plans),
    path("portfolio-construction/plans/<int:plan_id>/goals/",construction_views.plan_goals),
    path("portfolio-construction/goals/<int:goal_id>/",construction_views.goal_detail),
    path("portfolio-construction/goals/<int:goal_id>/eligible-strategies/",construction_views.goal_eligible_strategies),
    path("portfolio-construction/goals/<int:goal_id>/selections/",construction_views.goal_selections),
    path("portfolio-construction/selections/<int:selection_id>/",construction_views.selection_detail),
    path("portfolio-construction/preview/",construction_views.preview),
    path("portfolio-construction/runs/",construction_views.runs),
    path("portfolio-construction/runs/<int:run_id>/",construction_views.runs),
    path("portfolio-construction/runs/<int:run_id>/apply/",construction_views.apply),
]
urlpatterns += [path("api/v1/" + str(p.pattern),p.callback,p.default_args) for p in new_api]
if settings.APP_BASE_PATH:
    prefix = settings.APP_BASE_PATH.strip("/") + "/"
    urlpatterns += [path(prefix + "healthz", views.health),path(prefix + "metrics",streaming_views.prometheus_metrics)] + [path(prefix + f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
    urlpatterns += [path(prefix + "api/v1/" + str(p.pattern),p.callback,p.default_args) for p in new_api]
