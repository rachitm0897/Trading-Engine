import pytest
from apps.accounts.models import BrokerAccount
from apps.broker_gateway.models import BrokerSyncCursor
from apps.broker_gateway.sync import sync_events
from apps.execution.models import Fill
from apps.oms.models import Order
from apps.portfolios.models import PortfolioPosition, TradingPortfolio

pytestmark=pytest.mark.django_db

class FakeGateway:
    def __init__(self, events): self._events=events; self.acked=0
    def events(self, after=0): return [event for event in self._events if event["id"]>after]
    def ack_events(self, sequence): self.acked=sequence

def event(sequence, kind, rows): return {"id":sequence,"event_type":f"snapshot.{kind}","payload":{"value":rows}}

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

