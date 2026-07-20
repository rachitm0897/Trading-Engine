from django.db import transaction
from django.conf import settings
from django.utils import timezone
from apps.broker_gateway.client import GatewayClient, GatewayRoute
from apps.audit.models import OutboxEvent
from .models import BrokerContract, Instrument


def _gateway(gateway=None,gateway_session=None):
    if gateway is not None:return gateway
    if gateway_session is None:
        if settings.BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED:
            return GatewayClient(GatewayRoute(
                session_id="static-development",
                base_url=settings.STATIC_DEVELOPMENT_IB_GATEWAY_URL,
                service_token=settings.STATIC_DEVELOPMENT_GATEWAY_SERVICE_TOKEN,
            ))
        raise ValueError("A broker gateway session is required")
    return GatewayClient(gateway_session,require_commands=True)


def search_broker_instruments(query, gateway=None, gateway_session=None):
    query=str(query or "").strip()
    if len(query)<1:raise ValueError("Instrument search query is required")
    rows=_gateway(gateway,gateway_session).search_contracts(query)
    results=[]
    for row in rows:
        conid=int(row.get("conid") or 0)
        if conid<=0 or not row.get("symbol"):continue
        existing=BrokerContract.objects.select_related("instrument").filter(conid=conid).first()
        results.append({"symbol":row.get("symbol") or "","local_symbol":row.get("local_symbol") or row.get("symbol") or "",
            "conid":conid,"asset_class":row.get("asset_class") or "","exchange":row.get("exchange") or "",
            "primary_exchange":row.get("primary_exchange") or "","currency":row.get("currency") or "",
            "description":row.get("description") or "","instrument_id":existing.instrument_id if existing else None})
    return results


def publish_instrument_registry(contract):
    instrument=contract.instrument
    event,_=OutboxEvent.objects.get_or_create(idempotency_key=f"instrument-registry:{contract.conid}",defaults={
        "topic":"instrument.registry.v1","event_type":"instrument.registry.updated","aggregate_type":"instrument",
        "aggregate_id":str(instrument.pk),"partition_key":str(contract.conid),"payload":{"instrument_id":instrument.pk,
        "conid":contract.conid,"symbol":instrument.symbol,"local_symbol":contract.local_symbol,
        "asset_class":instrument.asset_class,"exchange":instrument.exchange,"primary_exchange":contract.primary_exchange,
        "currency":instrument.currency,"active":instrument.active and instrument.tradable}})
    return event


def resolve_instrument(*, instrument_id=None, ticker=None, asset_class="STK", exchange="SMART", currency="USD",
                       primary_exchange=None, conid=None, local_symbol=None, description=None, qualify=True, gateway=None,
                       gateway_session=None):
    """Resolve operator input to a canonical instrument and qualified IBKR contract."""
    selected_contract=BrokerContract.objects.select_related("instrument").filter(conid=int(conid)).first() if conid else None
    if selected_contract:
        if qualify:
            selected_instrument=selected_contract.instrument
            payload={"symbol":selected_instrument.symbol,"asset_class":selected_instrument.asset_class,
                     "exchange":selected_instrument.exchange,"currency":selected_instrument.currency,
                     "primary_exchange":primary_exchange or selected_contract.primary_exchange or selected_instrument.primary_exchange,
                     "local_symbol":local_symbol or selected_contract.local_symbol or selected_instrument.symbol,
                     "description":description or selected_contract.description}
            payload["conid"]=int(conid)
            result=_gateway(gateway,gateway_session).qualify_contract_exact(payload,f"qualify:conid:{int(conid)}")
            if int(result.get("conid") or 0)!=int(conid):raise ValueError("IBKR qualified a different contract than the selected conId")
            selected_contract=record_qualified_contract(selected_instrument,result)
        publish_instrument_registry(selected_contract)
        return selected_contract.instrument,selected_contract,None
    if instrument_id:
        instrument = Instrument.objects.get(pk=instrument_id)
    else:
        symbol = str(ticker or "").strip().upper()
        if not symbol:
            raise ValueError("ticker or instrument_id is required")
        choices = Instrument.objects.filter(symbol=symbol, asset_class=asset_class, currency=currency)
        if primary_exchange:
            choices = choices.filter(primary_exchange=primary_exchange)
        if choices.count() > 1 and not exchange:
            raise ValueError("Ticker is ambiguous; select an exchange")
        instrument = choices.filter(exchange=exchange).first() or (choices.first() if not conid else None)
        if instrument is None:
            instrument = Instrument.objects.create(symbol=symbol, asset_class=asset_class, exchange=exchange,
                primary_exchange=primary_exchange or "",currency=currency)
    if not instrument.active or not instrument.tradable:
        raise ValueError("Instrument is not active/tradable")
    contract = BrokerContract.objects.filter(instrument=instrument).first()
    if contract or not qualify:
        return instrument, contract, None
    client=_gateway(gateway,gateway_session)
    payload={"symbol":instrument.symbol,"asset_class":instrument.asset_class,"exchange":instrument.exchange,
        "currency":instrument.currency,"primary_exchange":primary_exchange or instrument.primary_exchange,
        "local_symbol":local_symbol or "","description":description or ""}
    if conid:
        payload["conid"]=int(conid)
        result=client.qualify_contract_exact(payload,f"qualify:conid:{int(conid)}")
        if int(result.get("conid") or 0)!=int(conid):raise ValueError("IBKR qualified a different contract than the selected conId")
        return instrument,record_qualified_contract(instrument,result),None
    command = client.qualify_contract(payload,f"qualify:instrument:{instrument.pk}")
    return instrument, None, command


@transaction.atomic
def record_qualified_contract(instrument, result):
    if not result.get("conid"):
        raise ValueError("IBKR qualification result has no conId")
    previous=BrokerContract.objects.filter(instrument=instrument).values(
        "conid","primary_exchange","local_symbol").first()
    contract=BrokerContract.objects.update_or_create(instrument=instrument, defaults={"conid":int(result["conid"]),
        "primary_exchange":result.get("primary_exchange", ""), "local_symbol":result.get("local_symbol", instrument.symbol),
        "description":result.get("description", ""),"qualified_at":timezone.now()})[0]
    publish_instrument_registry(contract)
    from .models import InstrumentProviderMapping
    mapping,_=InstrumentProviderMapping.objects.get_or_create(instrument=instrument,provider="FINNHUB")
    identity=(contract.conid,contract.primary_exchange,contract.local_symbol)
    if previous and identity!=(previous["conid"],previous["primary_exchange"],previous["local_symbol"]):
        mapping.status="PENDING";mapping.verification_method="";mapping.verified_at=None
        mapping.last_error="IBKR contract identity changed; Finnhub mapping must be reverified"
        mapping.save(update_fields=["status","verification_method","verified_at","last_error","updated_at"])
    return contract
