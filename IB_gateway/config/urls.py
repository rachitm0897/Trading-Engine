from django.urls import include, path
from gateway_service import views
api=[
 path("health/",views.health),path("session/",views.session),path("session/reconnect/",views.reconnect),
 path("accounts/",views.accounts),path("account-summary/",views.account_summary),path("positions/",views.positions),path("open-orders/",views.open_orders),path("completed-orders/",views.completed_orders),path("executions/",views.executions),
 path("contracts/search/",views.contract_search),path("contracts/qualify/",views.qualify),path("commands/<int:command_id>/",views.command_detail),
 path("market-data/history/",views.historical_data),
 path("market-data/schedule/",views.historical_schedule),
 path("market-data/subscriptions/",views.market_subscription),path("market-data/subscriptions/cancel/",views.market_subscription,{"action":"cancel"}),
 path("orders/",views.orders),path("orders/<str:internal_id>/",views.orders),path("orders/<str:internal_id>/cancel/",views.cancel),
 path("events/",views.events),path("events/ack/",views.ack),path("kill-switch/",views.kill_switch),
]
urlpatterns = [
    path("healthz", views.healthz),
    path("api/v1/", include(api)),
]
