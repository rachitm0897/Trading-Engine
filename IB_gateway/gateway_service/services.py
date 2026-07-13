from django.db import transaction
from django.utils import timezone
from .models import GatewayCommand, GatewayEvent, GatewayOrderReference, GatewaySession

@transaction.atomic
def enqueue(command_type, payload, idempotency_key):
    command, _ = GatewayCommand.objects.get_or_create(idempotency_key=idempotency_key, defaults={"command_type":command_type, "payload":payload})
    return command

def persist_event(event_key, event_type, payload):
    event, _ = GatewayEvent.objects.get_or_create(event_key=event_key, defaults={"event_type":event_type, "payload":payload})
    GatewaySession.objects.update_or_create(pk=1, defaults={"last_callback_at":timezone.now()})
    return event

def process_command(command, adapter):
    command.attempts += 1; command.status="PROCESSING"; command.save(update_fields=["attempts","status","updated_at"])
    if command.command_type == "RECONNECT":
        if adapter.is_connected(): adapter.disconnect()
        result = adapter.connect(); state = adapter.refresh_state(); result.update(state)
    elif command.command_type == "SEARCH_CONTRACTS": result = {"results":adapter.search_contracts(command.payload["query"])}
    elif command.command_type == "QUALIFY": result = adapter.qualify_contract(command.payload)
    elif command.command_type == "PLACE_ORDER": result = adapter.place_order(command.payload)
    elif command.command_type == "MODIFY_ORDER": result = adapter.modify_order(command.payload)
    elif command.command_type == "CANCEL_ORDER": result = adapter.cancel_order(command.payload)
    elif command.command_type == "REFRESH": result = adapter.refresh_state()
    elif command.command_type == "KILL_SWITCH": adapter.killed = bool(command.payload.get("enabled", True)); result={"enabled":adapter.killed}
    else: raise ValueError("Unsupported command")
    if command.command_type in {"PLACE_ORDER","MODIFY_ORDER","CANCEL_ORDER"}:
        GatewayOrderReference.objects.update_or_create(internal_id=command.payload["internal_id"], defaults={"broker_order_id":str(result.get("broker_order_id","")), "permanent_id":str(result.get("permanent_id","")), "last_status":result.get("status","")})
    command.result=result; command.status="COMPLETED"; command.save(update_fields=["result","status","updated_at"])
    persist_event(f"command:{command.pk}:completed", f"command.{command.command_type.lower()}.completed", {"command_id":command.pk, **result})
    return result
