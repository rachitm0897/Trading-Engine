from django.conf import settings
from django.urls import path
from gateway_service import views
api=[
 path("health/",views.health),path("session/",views.session),path("session/reconnect/",views.reconnect),
 path("accounts/",views.accounts),path("account-summary/",views.account_summary),path("positions/",views.positions),path("open-orders/",views.open_orders),path("completed-orders/",views.completed_orders),path("executions/",views.executions),
 path("contracts/search/",views.contract_search),path("contracts/qualify/",views.qualify),path("commands/<int:command_id>/",views.command_detail),
 path("orders/",views.orders),path("orders/<str:internal_id>/",views.orders),path("orders/<str:internal_id>/cancel/",views.cancel),
 path("events/",views.events),path("events/ack/",views.ack),path("kill-switch/",views.kill_switch),
]
urlpatterns=[path("healthz",views.healthz)]+[path(f"api/v1/{p.pattern}",p.callback) for p in api]
if settings.APP_BASE_PATH:
 prefix=settings.APP_BASE_PATH.strip("/")+"/"; urlpatterns += [path(prefix+"healthz",views.healthz)]+[path(prefix+f"api/v1/{p.pattern}",p.callback) for p in api]
