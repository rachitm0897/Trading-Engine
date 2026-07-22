import pytest
from apps.instruments.models import BrokerContract, Instrument
from apps.instruments.services import resolve_instrument, search_broker_instruments
from apps.audit.models import OutboxEvent

pytestmark=pytest.mark.django_db


class BrokerStub:
    result={"symbol":"BHP","local_symbol":"BHP","conid":12345,"asset_class":"STK","exchange":"SMART",
        "primary_exchange":"ASX","currency":"AUD","description":"BHP Group Limited"}
    def search_contracts(self, query):return [{**self.result},{**self.result,"conid":67890,"primary_exchange":"LSE","currency":"GBP"}]
    def qualify_contract_exact(self, payload, key):return {**self.result,"conid":payload["conid"],"qualified":True}


def test_search_returns_multiple_unseeded_exact_contracts():
    rows=search_broker_instruments("BHP",BrokerStub())
    assert len(rows)==2 and {row["primary_exchange"] for row in rows}=={"ASX","LSE"}
    assert all(row["instrument_id"] is None for row in rows)


def test_selected_conid_is_qualified_and_persisted_exactly():
    row=BrokerStub.result
    instrument,contract,command=resolve_instrument(ticker=row["symbol"],asset_class=row["asset_class"],exchange=row["exchange"],
        primary_exchange=row["primary_exchange"],currency=row["currency"],conid=row["conid"],local_symbol=row["local_symbol"],
        description=row["description"],gateway=BrokerStub())
    assert command is None and contract.conid==row["conid"] and contract.description==row["description"]
    assert instrument.primary_exchange=="ASX" and BrokerContract.objects.get(conid=12345).instrument==instrument
    assert Instrument.objects.count()==1
    registry=OutboxEvent.objects.get(topic="instrument.registry.v1")
    assert registry.payload["conid"]==12345 and registry.payload["instrument_id"]==instrument.pk


def test_existing_selected_conid_is_requalified_from_broker():
    instrument=Instrument.objects.create(symbol="BHP",asset_class="STK",exchange="SMART",currency="AUD")
    BrokerContract.objects.create(instrument=instrument,conid=12345,local_symbol="BHP",qualified_at=None)
    resolved,contract,command=resolve_instrument(
        instrument_id=instrument.pk,conid=12345,primary_exchange="ASX",local_symbol="BHP",
        description="BHP Group Limited",gateway=BrokerStub(),
    )
    assert command is None and resolved==instrument
    assert contract.qualified_at is not None and contract.primary_exchange=="ASX"
    assert contract.description=="BHP Group Limited"
