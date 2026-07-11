from decimal import Decimal
import pytest
from django.utils import timezone
from apps.accounts.models import BrokerAccount
from apps.allocation.models import RebalancePolicy
from apps.instruments.models import Instrument
from apps.oms.models import Order, OrderIntent
from apps.portfolios.models import PortfolioPosition, TradingPortfolio
from apps.rebalancing.services import advance_rebalance, plan_rebalance, recover_incomplete
from apps.strategies.models import StrategyAllocation, StrategyRun, StrategyTarget, TradingStrategy

pytestmark=pytest.mark.django_db


def setup_case():
    account=BrokerAccount.objects.create(account_id="DU1",net_liquidation=1000,available_cash=0)
    portfolio=TradingPortfolio.objects.create(name="P",account=account)
    old=Instrument.objects.create(symbol="OLD"); new=Instrument.objects.create(symbol="NEW")
    PortfolioPosition.objects.create(portfolio=portfolio,instrument=old,quantity=10,market_price=100)
    strategy=TradingStrategy.objects.create(name="S",strategy_type="fixed_weight")
    alloc=StrategyAllocation.objects.create(portfolio=portfolio,strategy=strategy,weight=1)
    run=StrategyRun.objects.create(strategy=strategy,input_hash="x",status="COMPLETED",completed_at=timezone.now())
    StrategyTarget.objects.create(run=run,instrument=new,target_weight="0.5")
    policy=RebalancePolicy.objects.create(portfolio=portfolio,maximum_turnover="2",mode="PAPER",partial_fill_threshold="0.95")
    return account,portfolio,old,new,policy


def test_netting_lot_rounding_suppression_and_sell_before_buy():
    account,portfolio,old,new,policy=setup_case()
    run=plan_rebalance(portfolio,"MANUAL","reb-1",prices={old.pk:100,new.pk:100},nav=1000,mode="PAPER",strict_market_state=False)
    sell=OrderIntent.objects.get(rebalance=run,side="SELL"); buy=OrderIntent.objects.get(rebalance=run,side="BUY")
    assert sell.quantity==10 and sell.eligible and buy.quantity==5 and not buy.eligible and run.phase=="SELLS"
    assert run.targets.get(instrument=new).drift==Decimal("0.5")


def test_partial_fill_recalculation_and_restart_do_not_duplicate():
    account,portfolio,old,new,policy=setup_case()
    run=plan_rebalance(portfolio,"MANUAL","reb-2",prices={old.pk:100,new.pk:100},nav=1000,mode="PAPER",strict_market_state=False)
    sell=OrderIntent.objects.get(rebalance=run,side="SELL")
    order=Order.objects.create(intent=sell,internal_id="sell",status="PARTIALLY_FILLED",quantity=10,filled_quantity=5)
    advance_rebalance(run); assert not OrderIntent.objects.get(rebalance=run,side="BUY").eligible
    order.status="FILLED";order.filled_quantity=10;order.save();account.available_cash=1000;account.save()
    position=PortfolioPosition.objects.get(portfolio=portfolio,instrument=old);position.quantity=0;position.save()
    advance_rebalance(run); assert OrderIntent.objects.get(rebalance=run,side="BUY").eligible
    count=OrderIntent.objects.count();recover_incomplete();recover_incomplete();assert OrderIntent.objects.count()==count


def test_shadow_preview_never_creates_intents():
    account,portfolio,old,new,policy=setup_case()
    run=plan_rebalance(portfolio,"MANUAL","reb-shadow",prices={old.pk:100,new.pk:100},nav=1000,mode="SHADOW",strict_market_state=False)
    assert run.phase=="SHADOW_COMPLETE" and not OrderIntent.objects.filter(rebalance=run).exists()
