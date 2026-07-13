from django.db import transaction
from django.utils import timezone
from apps.broker_gateway.client import GatewayClient
from .models import BrokerContract, Instrument


def search_broker_instruments(query, gateway=None):
    query=str(query or "").strip()
    if len(query)<1:raise ValueError("Instrument search query is required")
    rows=(gateway or GatewayClient()).search_contracts(query)
    results=[]
    for row in rows:
        conid=int(row.get("conid") or 0)
        if not conid:continue
        existing=BrokerContract.objects.select_related("instrument").filter(conid=conid).first()
        results.append({"symbol":row.get("symbol") or "","local_symbol":row.get("local_symbol") or row.get("symbol") or "",
            "conid":conid,"asset_class":row.get("asset_class") or "","exchange":row.get("exchange") or "",
            "primary_exchange":row.get("primary_exchange") or "","currency":row.get("currency") or "",
            "description":row.get("description") or "","instrument_id":existing.instrument_id if existing else None})
    return results


def resolve_instrument(*, instrument_id=None, ticker=None, asset_class="STK", exchange="SMART", currency="USD",
                       primary_exchange=None, conid=None, local_symbol=None, description=None, qualify=True, gateway=None):
    """Resolve operator input to a canonical instrument and qualified IBKR contract."""
    selected_contract=BrokerContract.objects.select_related("instrument").filter(conid=int(conid)).first() if conid else None
    if selected_contract:
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
    client=gateway or GatewayClient()
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
    return BrokerContract.objects.update_or_create(instrument=instrument, defaults={"conid":int(result["conid"]),
        "primary_exchange":result.get("primary_exchange", ""), "local_symbol":result.get("local_symbol", instrument.symbol),
        "description":result.get("description", ""),"qualified_at":timezone.now()})[0]
