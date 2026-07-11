import os
from pathlib import Path
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Write the runtime-only IBC configuration from environment secrets"
    def handle(self, *args, **options):
        target=Path("/home/ibgateway/ibc/config.ini")
        target.parent.mkdir(parents=True,exist_ok=True)
        content="\n".join([
            "[Logon]", f"IbLoginId={os.getenv('IB_USERNAME','')}", f"IbPassword={os.getenv('IB_PASSWORD','')}",
            f"TradingMode={os.getenv('IBC_TRADING_MODE','paper')}", "AcceptNonBrokerageAccountWarning=yes", "",
            "[Gateway]", "ReadOnlyApi=no", f"ExistingSessionDetectedAction=primary", f"AcceptIncomingConnectionAction=accept",
            f"TwoFactorAuthenticationTimeout={os.getenv('IBC_2FA_TIMEOUT','180')}", "",
            "[AutoRestart]", f"AutoRestartTime={os.getenv('IBC_AUTO_RESTART_TIME','11:45 PM')}",
        ])+"\n"
        target.write_text(content,encoding="utf-8"); target.chmod(0o600)
        self.stdout.write("IBC runtime configuration created")

