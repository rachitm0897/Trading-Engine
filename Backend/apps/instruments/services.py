from django.db import transaction
from django.utils import timezone
from apps.broker_gateway.client import GatewayClient
from .models import BrokerContract, Instrument


def resolve_instrument(*, instrument_id=None, ticker=None, asset_class="STK", exchange="SMART", currency="USD",
                       primary_exchange=None, qualify=True, gateway=None):
    """Resolve operator input to a canonical instrument and qualified IBKR contract."""
    if instrument_id:
        instrument = Instrument.objects.get(pk=instrument_id)
    else:
        symbol = str(ticker or "").strip().upper()
        if not symbol:
            raise ValueError("ticker or instrument_id is required")
        choices = Instrument.objects.filter(symbol=symbol, asset_class=asset_class, currency=currency)
        if primary_exchange:
            choices = choices.filter(broker_contract__primary_exchange=primary_exchange)
        if choices.count() > 1 and not exchange:
            raise ValueError("Ticker is ambiguous; select an exchange")
        instrument = choices.filter(exchange=exchange).first() or choices.first()
        if instrument is None:
            instrument = Instrument.objects.create(symbol=symbol, asset_class=asset_class, exchange=exchange, currency=currency)
    if not instrument.active or not instrument.tradable:
        raise ValueError("Instrument is not active/tradable")
    contract = BrokerContract.objects.filter(instrument=instrument).first()
    if contract or not qualify:
        return instrument, contract, None
    command = (gateway or GatewayClient()).qualify_contract({"symbol":instrument.symbol,"asset_class":instrument.asset_class,
        "exchange":instrument.exchange,"currency":instrument.currency,"primary_exchange":primary_exchange or ""},
        f"qualify:instrument:{instrument.pk}")
    return instrument, None, command


@transaction.atomic
def record_qualified_contract(instrument, result):
    if not result.get("conid"):
        raise ValueError("IBKR qualification result has no conId")
    return BrokerContract.objects.update_or_create(instrument=instrument, defaults={"conid":int(result["conid"]),
        "primary_exchange":result.get("primary_exchange", ""), "local_symbol":result.get("local_symbol", instrument.symbol),
        "qualified_at":timezone.now()})[0]
