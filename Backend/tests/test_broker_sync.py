import pytest
from apps.accounts.models import BrokerAccount
from apps.broker_gateway.models import BrokerSyncCursor
from apps.broker_gateway.models import BrokerPositionSnapshot
from apps.broker_gateway.sync import sync_events, sync_positions
from apps.execution.models import Fill
from apps.instruments.models import Instrument
from apps.oms.models import Order
from apps.portfolios.models import PortfolioPosition, TradingPortfolio

pytestmark=pytest.mark.django_db

class FakeGateway:
    def __init__(self, events): self._events=events; self.acked=0
    def events(self, after=0): return [event for event in self._events if event["id"]>after]
    def ack_events(self, sequence): self.acked=sequence

def event(sequence, kind, rows): return {"id":sequence,"event_type":f"snapshot.{kind}","payload":{"value":rows}}

def position_event(sequence, account, rows, *, complete=True, snapshot_id=None):
    return {"id":sequence,"event_type":"snapshot.positions","payload":{"value":rows,"account":account,
        "complete":complete,"snapshot_id":snapshot_id or f"snapshot-{sequence}-{account}"}}

def test_gateway_snapshots_create_broker_truth_projections_and_ledgers():
    contract={"account":"DU123","conid":265598,"symbol":"AAPL","local_symbol":"AAPL","asset_class":"STK","exchange":"SMART","primary_exchange":"NASDAQ","currency":"USD"}
    events=[
        event(1,"accounts",[{"account_id":"DU123"}]),
        event(2,"account_summary",[
            {"account":"DU123","tag":"NetLiquidation","value":"125000","currency":"USD"},
            {"account":"DU123","tag":"AvailableFunds","value":"40000","currency":"USD"},
            {"account":"DU123","tag":"BuyingPower","value":"160000","currency":"USD"},
        ]),
        event(3,"open_orders",[{**contract,"internal_id":"","broker_order_id":"77","permanent_id":"9001","side":"BUY","quantity":"5","order_type":"LMT","limit_price":"100","stop_price":None,"time_in_force":"DAY","status":"Submitted","filled_quantity":"0","average_fill_price":"0"}]),
        event(4,"executions",[{**contract,"execution_id":"E-1","broker_order_id":"77","permanent_id":"9001","side":"BOT","quantity":"5","price":"99.50","commission":"1.25","executed_at":"2026-07-11T09:00:00+00:00"}]),
        event(5,"positions",[{**contract,"quantity":"5","average_cost":"99.75","market_price":"101.00"}]),
    ]
    gateway=FakeGateway(events)
    assert sync_events(gateway)==5 and gateway.acked==5
    account=BrokerAccount.objects.get(account_id="DU123")
    assert account.net_liquidation==125000 and account.available_cash==40000
    assert TradingPortfolio.objects.get(account=account).name=="IBKR DU123"
    assert PortfolioPosition.objects.get(portfolio__account=account).quantity==5
    assert Order.objects.get(broker_permanent_id="9001").status=="FILLED"
    assert Fill.objects.get(execution_id="E-1").commission==pytest.approx(1.25)
    assert BrokerSyncCursor.objects.get().last_sequence==5
    assert sync_events(gateway)==0 and Fill.objects.count()==1


def _position(account, quantity, *, conid=265598, symbol="AAPL"):
    return {"account":account,"conid":conid,"symbol":symbol,"local_symbol":symbol,"asset_class":"STK",
        "exchange":"SMART","primary_exchange":"NASDAQ","currency":"USD","quantity":str(quantity),
        "average_cost":"100","market_price":"101"}


def test_complete_snapshot_is_scoped_to_one_account_with_same_contract():
    account_a=BrokerAccount.objects.create(account_id="DU-A")
    account_b=BrokerAccount.objects.create(account_id="DU-B")
    portfolio_a=TradingPortfolio.objects.create(account=account_a,name="A")
    portfolio_b=TradingPortfolio.objects.create(account=account_b,name="B")
    instrument=Instrument.objects.create(symbol="AAPL",primary_exchange="NASDAQ")
    from apps.instruments.models import BrokerContract
    BrokerContract.objects.create(instrument=instrument,conid=265598)
    PortfolioPosition.objects.create(portfolio=portfolio_a,instrument=instrument,quantity=1,average_cost=80)
    PortfolioPosition.objects.create(portfolio=portfolio_b,instrument=instrument,quantity=9,average_cost=90)

    sync_events(FakeGateway([position_event(1,"DU-A",[_position("DU-A",3)])]))

    assert PortfolioPosition.objects.get(portfolio=portfolio_a,instrument=instrument).quantity==3
    untouched=PortfolioPosition.objects.get(portfolio=portfolio_b,instrument=instrument)
    assert untouched.quantity==9 and untouched.average_cost==90


def test_empty_complete_snapshot_zeros_only_the_target_account():
    account_a=BrokerAccount.objects.create(account_id="DU-A")
    account_b=BrokerAccount.objects.create(account_id="DU-B")
    portfolio_a=TradingPortfolio.objects.create(account=account_a,name="A")
    portfolio_b=TradingPortfolio.objects.create(account=account_b,name="B")
    instrument=Instrument.objects.create(symbol="MSFT")
    PortfolioPosition.objects.create(portfolio=portfolio_a,instrument=instrument,quantity=4,average_cost=10,market_price=11)
    PortfolioPosition.objects.create(portfolio=portfolio_b,instrument=instrument,quantity=7,average_cost=20,market_price=21)

    sync_events(FakeGateway([position_event(1,"DU-A",[])]))

    target=PortfolioPosition.objects.get(portfolio=portfolio_a,instrument=instrument)
    other=PortfolioPosition.objects.get(portfolio=portfolio_b,instrument=instrument)
    assert (target.quantity,target.average_cost,target.market_price)==(0,0,0)
    assert (other.quantity,other.average_cost,other.market_price)==(7,20,21)


def test_partial_snapshot_is_audited_but_not_applied():
    account=BrokerAccount.objects.create(account_id="DU-A")
    portfolio=TradingPortfolio.objects.create(account=account,name="A")
    instrument=Instrument.objects.create(symbol="AAPL",primary_exchange="NASDAQ")
    from apps.instruments.models import BrokerContract
    BrokerContract.objects.create(instrument=instrument,conid=265598)
    PortfolioPosition.objects.create(portfolio=portfolio,instrument=instrument,quantity=8,average_cost=75)

    sync_events(FakeGateway([position_event(1,"DU-A",[_position("DU-A",2)],complete=False)]))

    current=PortfolioPosition.objects.get(portfolio=portfolio,instrument=instrument)
    snapshot=BrokerPositionSnapshot.objects.get()
    assert (current.quantity,current.average_cost)==(8,75)
    assert snapshot.status=="INCOMPLETE" and snapshot.complete is False


def test_duplicate_complete_snapshot_is_applied_once():
    rows=[_position("DU-A",5)]
    gateway=FakeGateway([
        position_event(1,"DU-A",rows,snapshot_id="same-snapshot"),
        position_event(2,"DU-A",rows,snapshot_id="same-snapshot"),
    ])
    assert sync_events(gateway)==2
    snapshot=BrokerPositionSnapshot.objects.get(snapshot_key="same-snapshot")
    assert snapshot.status=="COMPLETED" and snapshot.attempt_count==1
    assert PortfolioPosition.objects.get(portfolio__account__account_id="DU-A").quantity==5


def test_snapshot_failure_rolls_back_all_position_changes_and_is_audited(monkeypatch):
    account=BrokerAccount.objects.create(account_id="DU-A")
    portfolio=TradingPortfolio.objects.create(account=account,name="A")
    instrument=Instrument.objects.create(symbol="AAPL",primary_exchange="NASDAQ")
    from apps.instruments.models import BrokerContract
    BrokerContract.objects.create(instrument=instrument,conid=265598)
    PortfolioPosition.objects.create(portfolio=portfolio,instrument=instrument,quantity=9,average_cost=90)
    from apps.broker_gateway import sync as sync_module
    real_ensure=sync_module.ensure_instrument
    def fail_second(row):
        if row.get("symbol")=="FAIL":
            raise RuntimeError("mid-snapshot failure")
        return real_ensure(row)
    monkeypatch.setattr(sync_module,"ensure_instrument",fail_second)
    rows=[_position("DU-A",2),_position("DU-A",1,conid=999,symbol="FAIL")]

    with pytest.raises(RuntimeError,match="mid-snapshot failure"):
        sync_positions(rows,account_id="DU-A",complete=True,snapshot_key="failed-snapshot")

    current=PortfolioPosition.objects.get(portfolio=portfolio,instrument=instrument)
    snapshot=BrokerPositionSnapshot.objects.get(snapshot_key="failed-snapshot")
    assert (current.quantity,current.average_cost)==(9,90)
    assert snapshot.status=="FAILED" and "mid-snapshot failure" in snapshot.last_error
