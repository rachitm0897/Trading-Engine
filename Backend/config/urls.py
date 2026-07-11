from django.conf import settings
from django.urls import path
from apps.core import views

api_patterns = [
    path("system/", views.system), path("gateway/", views.gateway), path("accounts/", views.accounts),
    path("instruments/", views.instruments), path("portfolios/", views.portfolios), path("positions/", views.positions),
    path("strategies/", views.strategies), path("strategy-runs/", views.strategy_runs), path("rebalances/", views.rebalances),
    path("orders/", views.orders), path("orders/<str:internal_id>/", views.orders), path("orders/<str:internal_id>/cancel/", views.orders, {"action":"cancel"}), path("executions/", views.executions), path("reconciliation/", views.reconciliation),
    path("risk/", views.risk), path("audit/", views.audit),
]
urlpatterns = [path("healthz", views.health)] + [path(f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
if settings.APP_BASE_PATH:
    prefix = settings.APP_BASE_PATH.strip("/") + "/"
    urlpatterns += [path(prefix + "healthz", views.health)] + [path(prefix + f"api/v1/{p.pattern}", p.callback, p.default_args) for p in api_patterns]
