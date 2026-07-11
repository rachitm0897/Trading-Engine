import fcntl, os, socket, time
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from broker.factory import create_adapter
from gateway_service.models import GatewayCommand, GatewayEvent, GatewayHealthSnapshot, GatewaySession
from gateway_service.services import persist_event, process_command

class Command(BaseCommand):
    help = "Run the sole process allowed to own the TWS connection"
    def handle(self,*args,**options):
        lock=open("/tmp/ibkr-broker-owner.lock","w")
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError("Another broker connection owner is already running")
        owner=f"{socket.gethostname()}:{os.getpid()}"; adapter=create_adapter()
        session,_=GatewaySession.objects.update_or_create(pk=1,defaults={"state":"CONNECTING","mode":settings.IBC_TRADING_MODE,"reconciled":False,"connection_owner":owner})
        backoff=1
        while True:
            close_old_connections()
            try:
                if not adapter.is_connected():
                    adapter.connect(); state=adapter.refresh_state()
                    GatewaySession.objects.filter(pk=1).update(state="CONNECTED",reconciled=bool(state.get("reconciled")),last_callback_at=timezone.now())
                    for key in ("accounts","positions","open_orders","executions"):
                        persist_event(f"snapshot:{key}:{time.time_ns()}",f"snapshot.{key}",{"value":state.get(key,[])})
                    persist_event(f"connected:{time.time_ns()}","session.connected",{"reconciled":state.get("reconciled",False)})
                    backoff=1
                command=GatewayCommand.objects.filter(status="PENDING").order_by("id").first()
                if command:
                    try: process_command(command,adapter)
                    except Exception as exc:
                        command.status="FAILED"; command.error=str(exc)[:1000]; command.save(update_fields=["status","error","updated_at"])
                        persist_event(f"command:{command.pk}:failed","command.failed",{"command_id":command.pk,"error":str(exc)[:500]})
                else: time.sleep(0.2)
            except Exception as exc:
                GatewaySession.objects.filter(pk=1).update(state="DISCONNECTED",reconciled=False,last_callback_at=timezone.now())
                GatewayHealthSnapshot.objects.create(connected=False,reconciled=False,details={"error":str(exc)[:500]})
                time.sleep(min(backoff,30)); backoff=min(backoff*2,30)

