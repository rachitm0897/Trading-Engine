import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.broker_gateway.client import GatewayClient,GatewayError
from apps.strategies.models import StrategyInstance
from apps.strategies.plugins import get_plugin
from .models import MarketDataSubscription


def _requirements(instrument,timeframe,gateway_session=None):
    query=StrategyInstance.objects.filter(enabled=True,instrument=instrument,timeframe=timeframe)
    if gateway_session is not None:query=query.filter(portfolio__gateway_session=gateway_session)
    instances=list(query.select_related("definition"))
    required=max((get_plugin(item.definition).warmup_bars(item.parameters) for item in instances),default=0)
    return instances,required+int(getattr(settings,"WARMUP_SAFETY_BARS",5)) if instances else 0


def reconcile_market_subscription(instrument,timeframe,gateway=None,force=False,connection_generation=None,gateway_session=None):
    contract=getattr(instrument,"broker_contract",None)
    if not contract:raise ValueError("Instrument does not have a qualified IBKR contract")
    gateway_session=gateway_session or getattr(gateway,"gateway_session",None)
    instances,history=_requirements(instrument,timeframe,gateway_session);count=len(instances)
    if gateway is None:
        if gateway_session is None:raise ValueError("A broker gateway session is required for market-data subscription routing")
        client=GatewayClient(gateway_session,require_commands=True)
    else:client=gateway
    generation=connection_generation
    if count and generation is None:
        health=client.health();generation=str(health.get("connection_generation") or "")
    action=None;payload=None;command_key=None
    with transaction.atomic():
        subscription,_=MarketDataSubscription.objects.select_for_update().get_or_create(gateway_session=gateway_session,instrument=instrument,timeframe=timeframe,
            defaults={"conid":contract.conid,"consumer_count":count,"required_history_bars":history})
        subscription.conid=contract.conid;subscription.consumer_count=count;subscription.required_history_bars=history
        if count:
            if subscription.active_provider=="FINNHUB" and not force:
                subscription.save(update_fields=["conid","consumer_count","required_history_bars","updated_at"])
                return subscription
            if not force and subscription.state in {"SUBSCRIBING","ACTIVE"} and subscription.gateway_connection_generation==generation:
                subscription.save(update_fields=["conid","consumer_count","required_history_bars","updated_at"]);return subscription
            subscription.request_id=uuid.uuid4();subscription.provider_generation=uuid.uuid4()
            subscription.active_provider="IBKR";subscription.fallback_state="PRIMARY";subscription.fallback_reason=""
            subscription.state="SUBSCRIBING";subscription.requested_at=timezone.now()
            subscription.gateway_connection_generation=generation
            subscription.save()
            session_key=str(gateway_session.pk) if gateway_session is not None else "explicit"
            payload={"subscription_key":f"{session_key}:{instrument.pk}:{timeframe}","instrument_id":instrument.pk,"conid":contract.conid,
                "symbol":instrument.symbol,"asset_class":instrument.asset_class,"exchange":instrument.exchange,
                "currency":instrument.currency,"timeframe":timeframe,"historical_bars":history,
                "provider":"IBKR","provider_generation":str(subscription.provider_generation)}
            command_key=f"market-subscribe:{session_key}:{subscription.pk}:{subscription.request_id}";action="subscribe"
        elif subscription.state!="INACTIVE" or subscription.consumer_count:
            subscription.request_id=uuid.uuid4();subscription.state="CANCELLING";subscription.requested_at=timezone.now();subscription.save()
            session_key=str(gateway_session.pk) if gateway_session is not None else "explicit"
            payload={"subscription_key":f"{session_key}:{instrument.pk}:{timeframe}"}
            command_key=f"market-cancel:{session_key}:{subscription.pk}:{subscription.request_id}";action="cancel"
        else:
            subscription.save(update_fields=["conid","consumer_count","required_history_bars","updated_at"])
            return subscription
        subscription_id=subscription.pk
    try:
        queued=(client.subscribe_market_data(payload,command_key) if action=="subscribe"
            else client.cancel_market_data(payload,command_key))
        MarketDataSubscription.objects.filter(pk=subscription_id).update(gateway_command_id=queued.get("command_id"),last_error="")
    except GatewayError as exc:
        MarketDataSubscription.objects.filter(pk=subscription_id).update(state="ERROR",last_error=str(exc)[:2000])
        if action=="subscribe":
            from apps.market_data.fallback import handle_ibkr_failure
            handle_ibkr_failure(MarketDataSubscription.objects.get(pk=subscription_id),message=str(exc),historical=True)
    return MarketDataSubscription.objects.get(pk=subscription_id)


def restore_market_subscriptions(gateway=None,gateway_session=None):
    if gateway is None and gateway_session is None:
        from apps.broker_gateway.models import BrokerGatewaySession
        total=0
        for session in BrokerGatewaySession.objects.filter(status=BrokerGatewaySession.Status.CONNECTED,commands_enabled=True):
            total+=restore_market_subscriptions(gateway_session=session)
        return total
    gateway_session=gateway_session or getattr(gateway,"gateway_session",None)
    client=gateway or GatewayClient(gateway_session);health=client.health()
    if not health.get("connected"):return 0
    generation=str(health.get("connection_generation") or "");restored=0
    instances=StrategyInstance.objects.filter(enabled=True)
    subscriptions=MarketDataSubscription.objects.all()
    if gateway_session is not None:
        instances=instances.filter(portfolio__gateway_session=gateway_session)
        subscriptions=subscriptions.filter(gateway_session=gateway_session)
    pairs=set(instances.values_list("instrument_id","timeframe"))
    pairs.update(subscriptions.values_list("instrument_id","timeframe"))
    from apps.instruments.models import Instrument
    for instrument_id,timeframe in pairs:
        instrument=Instrument.objects.select_related("broker_contract").get(pk=instrument_id)
        current=MarketDataSubscription.objects.filter(gateway_session=gateway_session,instrument=instrument,timeframe=timeframe).first()
        if current and current.active_provider=="FINNHUB" and current.consumer_count:
            continue
        force=bool(current and current.consumer_count and current.gateway_connection_generation!=generation)
        reconcile_market_subscription(instrument,timeframe,client,force=force,connection_generation=generation,gateway_session=gateway_session);restored+=int(force)
    return restored
