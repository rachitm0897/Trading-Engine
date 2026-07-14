from decimal import Decimal
import pytest
from apps.accounts.models import BrokerAccount
from apps.allocation.models import AllocationDecision, StrategyCapitalSnapshot
from apps.allocation.services import allocate_deposit, allocate_withdrawal, create_flow
from apps.portfolios.models import TradingPortfolio
from apps.strategies.models import StrategyAllocation, TradingStrategy

pytestmark=pytest.mark.django_db


def rows():
    return [{"id":1,"enabled":True,"target_share":"0.6","current":"400","maximum_share":"0.7","capacity":"1000","priority":1},
            {"id":2,"enabled":True,"target_share":"0.4","current":"500","maximum_share":"0.5","capacity":"1000","priority":2},
            {"id":3,"enabled":False,"target_share":"0.1","current":"0"}]


def test_deposit_is_deficit_weighted_capped_and_exact():
    allocated,remainder,computed=allocate_deposit("100","900",rows())
    assert allocated["1"]==Decimal("100.00") and allocated["2"]==0 and "3" not in allocated
    assert sum(allocated.values())+remainder==Decimal("100.00")


def test_zero_deficit_falls_back_to_target_shares():
    data=[{"id":1,"target_share":"0.6","current":"1000","maximum_share":"2","capacity":"2000"},{"id":2,"target_share":"0.4","current":"1000","maximum_share":"2","capacity":"2000"}]
    allocated,remainder,_=allocate_deposit("100","1000",data)
    assert allocated=={"1":Decimal("60.00"),"2":Decimal("40.00")} and remainder==0


def test_withdrawal_uses_cash_then_idle_surplus_and_liquidation():
    data=[{"id":1,"target_share":"0.5","current":"400","idle_cash":"50","priority":1},{"id":2,"target_share":"0.5","current":"300","idle_cash":"0","priority":2}]
    decisions=allocate_withdrawal("300","1000","100",data)
    assert [x["source"] for x in decisions[:3]]==["PORTFOLIO_CASH","STRATEGY_CASH","STRATEGY_SURPLUS"]
    assert any(x["source"]=="POSITION_LIQUIDATION" for x in decisions)
    assert sum(x["amount"] for x in decisions)==Decimal("300.00")


def test_flow_retry_is_idempotent_and_reserves_cash():
    account=BrokerAccount.objects.create(account_id="DU1",net_liquidation=1000,available_cash=0)
    portfolio=TradingPortfolio.objects.create(name="P",account=account,cash_buffer_pct="0.10")
    strategy=TradingStrategy.objects.create(name="S",strategy_type="fixed_weight",allocated_capital=0)
    StrategyAllocation.objects.create(portfolio=portfolio,strategy=strategy,weight=1)
    first=create_flow(portfolio,"DEPOSIT",200,"flow-1"); second=create_flow(portfolio,"DEPOSIT",200,"flow-1")
    assert first.pk==second.pk and first.unallocated_amount==Decimal("120.00")
    assert AllocationDecision.objects.count()==1
    strategy.refresh_from_db()
    assert strategy.allocated_capital == Decimal("80.00")
    assert StrategyCapitalSnapshot.objects.filter(allocation_run=first).count() == 1


def test_auto_without_enabled_optimization_configuration_uses_strategy_allocation():
    account=BrokerAccount.objects.create(account_id="DU-AUTO",net_liquidation=1000,available_cash=1000)
    portfolio=TradingPortfolio.objects.create(name="Auto strategy",account=account)
    strategy=TradingStrategy.objects.create(name="Auto S",strategy_type="fixed_weight",allocated_capital=100)
    StrategyAllocation.objects.create(portfolio=portfolio,strategy=strategy,weight=1)

    run=create_flow(portfolio,"DEPOSIT",100,"flow-auto-strategy",allocation_mode="AUTO")

    strategy.refresh_from_db()
    assert run.allocation_mode == "STRATEGY_ALLOCATION"
    assert run.optimization_run_id is None
    assert strategy.allocated_capital > Decimal("100")
    assert run.decisions.exists()
