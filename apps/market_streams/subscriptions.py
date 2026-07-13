import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.broker_gateway.client import GatewayClient
from apps.strategies.models import StrategyInstance
from apps.strategies.plugins import get_plugin
from .models import MarketDataSubscription


def _requirements(instrument,timeframe):
    instances=list(StrategyInstance.objects.filter(enabled=True,instrument=instrument,timeframe=timeframe).select_related("definition"))
    required=max((get_plugin(item.definition).warmup_bars(item.parameters) for item in instances),default=0)
    return instances,required+int(getattr(settings,"WARMUP_SAFETY_BARS",5)) if instances else 0


@transaction.atomic
def reconcile_market_subscription(instrument,timeframe,gateway=None,force=False,connection_generation=None):
    contract=getattr(instrument,"broker_contract",None)
    if not contract:raise ValueError("Instrument does not have a qualified IBKR contract")
    instances,history=_requirements(instrument,timeframe);count=len(instances)
    subscription,_=MarketDataSubscription.objects.select_for_update().get_or_create(instrument=instrument,timeframe=timeframe,
        defaults={"conid":contract.conid,"consumer_count":count,"required_history_bars":history})
    subscription.conid=contract.conid;subscription.consumer_count=count;subscription.required_history_bars=history
    client=gateway or GatewayClient()
    if count:
        generation=connection_generation
        if generation is None:
            health=client.health();generation=str(health.get("connection_generation") or "")
        if not force and subscription.state in {"SUBSCRIBING","ACTIVE"} and subscription.gateway_connection_generation==generation:
            subscription.save(update_fields=["conid","consumer_count","required_history_bars","updated_at"]);return subscription
        subscription.request_id=uuid.uuid4();subscription.state="SUBSCRIBING";subscription.requested_at=timezone.now()
        subscription.gateway_connection_generation=generation
        subscription.save()
        payload={"subscription_key":f"{instrument.pk}:{timeframe}","instrument_id":instrument.pk,"conid":contract.conid,
            "symbol":instrument.symbol,"asset_class":instrument.asset_class,"exchange":instrument.exchange,
            "currency":instrument.currency,"timeframe":timeframe,"historical_bars":history}
        try:
            queued=client.subscribe_market_data(payload,f"market-subscribe:{subscription.pk}:{subscription.request_id}")
            subscription.gateway_command_id=queued.get("command_id");subscription.save(update_fields=["gateway_command_id","updated_at"])
        except Exception as exc:
            subscription.state="ERROR";subscription.last_error=str(exc)[:2000];subscription.save(update_fields=["state","last_error","updated_at"])
        return subscription
    if subscription.state!="INACTIVE" or subscription.consumer_count:
        subscription.request_id=uuid.uuid4();subscription.state="CANCELLING";subscription.requested_at=timezone.now();subscription.save()
        try:
            queued=client.cancel_market_data({"subscription_key":f"{instrument.pk}:{timeframe}"},
                f"market-cancel:{subscription.pk}:{subscription.request_id}")
            subscription.gateway_command_id=queued.get("command_id");subscription.save(update_fields=["gateway_command_id","updated_at"])
        except Exception as exc:
            subscription.state="ERROR";subscription.last_error=str(exc)[:2000];subscription.save(update_fields=["state","last_error","updated_at"])
    else:subscription.save(update_fields=["conid","consumer_count","required_history_bars","updated_at"])
    return subscription


def restore_market_subscriptions(gateway=None):
    client=gateway or GatewayClient();health=client.health()
    if not health.get("connected"):return 0
    generation=str(health.get("connection_generation") or "");restored=0
    pairs=set(StrategyInstance.objects.filter(enabled=True).values_list("instrument_id","timeframe"))
    pairs.update(MarketDataSubscription.objects.values_list("instrument_id","timeframe"))
    from apps.instruments.models import Instrument
    for instrument_id,timeframe in pairs:
        instrument=Instrument.objects.select_related("broker_contract").get(pk=instrument_id)
        current=MarketDataSubscription.objects.filter(instrument=instrument,timeframe=timeframe).first()
        force=bool(current and current.consumer_count and current.gateway_connection_generation!=generation)
        reconcile_market_subscription(instrument,timeframe,client,force=force,connection_generation=generation);restored+=int(force)
    return restored
