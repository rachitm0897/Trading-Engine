import os
from django.core.management.base import BaseCommand
from apps.accounts.models import BrokerAccount
from apps.instruments.models import Instrument
from apps.portfolios.models import TradingPortfolio
from apps.strategies.models import TradingStrategy
from apps.strategies.models import StrategyAllocation

class Command(BaseCommand):
    help = "Create safe mock/paper defaults when BOOTSTRAP_DEMO_DATA is explicitly true"
    def handle(self,*args,**options):
        if os.getenv("BOOTSTRAP_DEMO_DATA","false").lower() != "true": return
        account,_=BrokerAccount.objects.get_or_create(account_id="DU-MOCK",defaults={"alias":"Local paper","available_cash":100000,"buying_power":200000,"net_liquidation":100000,"is_reconciled":True})
        portfolio,_=TradingPortfolio.objects.get_or_create(name="Local Paper",account=account)
        instruments=[]
        for symbol in ("AAPL","MSFT"):
            value,_=Instrument.objects.get_or_create(symbol=symbol,asset_class="STK",exchange="SMART",currency="USD")
            instruments.append(value)
        defaults={
            "fixed_weight":{"weights":{"AAPL":"0.50","MSFT":"0.50"}},
            "sma_trend":{"fast_window":20,"slow_window":50,"target_weight":"0.50"},
            "rsi_mean_reversion":{"rsi_window":14,"entry_threshold":30,"exit_threshold":70,"target_weight":"0.35"},
            "donchian_breakout":{"entry_window":20,"exit_window":10,"target_weight":"0.40"},
            "volatility_target_momentum":{"momentum_window":63,"volatility_window":20,"target_volatility":"0.12","maximum_weight":"0.50"},
        }
        for strategy_type,configuration in defaults.items():
            strategy,_=TradingStrategy.objects.get_or_create(name=strategy_type.replace("_"," ").title(),strategy_type=strategy_type,defaults={"configuration":configuration,"allocated_capital":20000,"maximum_target_weight":"0.50","enabled":strategy_type=="fixed_weight"})
            strategy.universe.set(instruments)
            if strategy_type == "fixed_weight": StrategyAllocation.objects.get_or_create(strategy=strategy,portfolio=portfolio,defaults={"weight":1})
        self.stdout.write(f"Paper defaults ready: account={account.account_id}, portfolio={portfolio.pk}")
