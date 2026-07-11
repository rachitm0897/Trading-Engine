from django.conf import settings
from django.urls import path
from apps.core import views
from apps.event_bus import views as streaming_views
from apps.allocation import views as allocation_views
from apps.rebalancing import views as rebalancing_views
from apps.position_sizing import views as sizing_views

api_patterns = [
    path("system/", views.system), path("gateway/", views.gateway), path("accounts/", views.accounts),
    path("instruments/", views.instruments), path("portfolios/", views.portfolios), path("positions/", views.positions),
    path("strategies/", views.strategies), path("strategy-runs/", views.strategy_runs), path("rebalances/", views.rebalances),
    path("orders/", views.orders), path("orders/<str:internal_id>/", views.orders), path("orders/<str:internal_id>/cancel/", views.orders, {"action":"cancel"}), path("executions/", views.executions), path("reconciliation/", views.reconciliation),
    path("risk/", views.risk), path("audit/", views.audit),
]
urlpatterns = [path("healthz", views.health),path("metrics",streaming_views.prometheus_metrics)] + [path(f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
new_api = [
    path("streaming/health/",streaming_views.health),path("streaming/topics/",streaming_views.topics),
    path("streaming/consumer-lag/",streaming_views.consumer_lag),path("streaming/dead-letter/",streaming_views.dead_letter),
    path("streaming/replay/",streaming_views.replay),
    path("allocations/policies/",allocation_views.policies),path("allocations/flows/",allocation_views.flows),
    path("allocations/runs/",allocation_views.runs),path("allocations/runs/<int:run_id>/",allocation_views.runs),
    path("rebalancing/policies/",rebalancing_views.policies),path("rebalancing/preview/",rebalancing_views.execute,{"preview":True}),
    path("rebalancing/run/",rebalancing_views.execute,{"preview":False}),path("rebalancing/runs/",rebalancing_views.runs),
    path("rebalancing/runs/<int:run_id>/",rebalancing_views.runs),path("position-sizing/preview/",sizing_views.preview),
    path("position-sizing/decisions/<int:decision_id>/",sizing_views.decision),
]
urlpatterns += [path("api/v1/" + str(p.pattern),p.callback,p.default_args) for p in new_api]
if settings.APP_BASE_PATH:
    prefix = settings.APP_BASE_PATH.strip("/") + "/"
    urlpatterns += [path(prefix + "healthz", views.health),path(prefix + "metrics",streaming_views.prometheus_metrics)] + [path(prefix + f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
    urlpatterns += [path(prefix + "api/v1/" + str(p.pattern),p.callback,p.default_args) for p in new_api]
