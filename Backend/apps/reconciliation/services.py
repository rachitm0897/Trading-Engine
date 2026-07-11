from collections import defaultdict
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import BrokerAccount
from apps.broker_gateway.client import GatewayClient
from apps.execution.models import Fill
from apps.instruments.models import BrokerContract
from apps.portfolios.models import PortfolioPosition
from .models import ReconciliationBreak, ReconciliationRun
from apps.audit.models import OutboxEvent

@transaction.atomic
def reconcile(trigger="manual", client=None):
    client=client or GatewayClient(); run=ReconciliationRun.objects.create(trigger=trigger)
    health=client.health()
    if not health.get("connected") or not health.get("reconciled"):
        ReconciliationBreak.objects.create(run=run,category="GATEWAY",severity="CRITICAL",internal_value={"expected":"CONNECTED_RECONCILED"},broker_value=health,material=True)
    broker_positions=defaultdict(Decimal)
    for row in client.positions() or []: broker_positions[str(row.get("conid"))] += Decimal(str(row.get("quantity",0)))
    internal_positions=defaultdict(Decimal)
    contracts={x.instrument_id:str(x.conid) for x in BrokerContract.objects.all()}
    for row in PortfolioPosition.objects.all():
        if row.instrument_id in contracts: internal_positions[contracts[row.instrument_id]] += row.quantity
    for conid in sorted(set(broker_positions)|set(internal_positions)):
        if broker_positions[conid] != internal_positions[conid]: ReconciliationBreak.objects.create(run=run,category="POSITION",severity="CRITICAL",internal_value={"conid":conid,"quantity":str(internal_positions[conid])},broker_value={"conid":conid,"quantity":str(broker_positions[conid])},material=True)
    broker_execs={str(x.get("execution_id")) for x in (client.executions() or []) if x.get("execution_id")}
    internal_execs=set(Fill.objects.values_list("execution_id",flat=True))
    for execution_id in sorted(broker_execs-internal_execs): ReconciliationBreak.objects.create(run=run,category="EXECUTION",severity="CRITICAL",internal_value={"execution_id":None},broker_value={"execution_id":execution_id},material=True)
    for execution_id in sorted(internal_execs-broker_execs): ReconciliationBreak.objects.create(run=run,category="EXECUTION",severity="WARNING",internal_value={"execution_id":execution_id},broker_value={"execution_id":None},material=False)
    for category in ("GATEWAY","POSITION","EXECUTION","ORDER","CASH","ACCOUNT"):
        if not run.breaks.filter(category=category,material=True).exists():
            ReconciliationBreak.objects.filter(category=category,material=True,resolved=False).exclude(run=run).update(resolved=True,resolution=f"Automatically resolved by clean reconciliation run {run.pk}")
    material=ReconciliationBreak.objects.filter(material=True,resolved=False).exists(); run.status="BLOCKED" if material else "COMPLETED"; run.completed_at=timezone.now(); run.save(update_fields=["status","completed_at"])
    BrokerAccount.objects.update(is_reconciled=not material)
    OutboxEvent.objects.create(topic="reconciliation.events.v1",event_type="reconciliation.completed",aggregate_type="system",
        aggregate_id=str(run.pk),partition_key="reconciliation",payload={"reconciliation_run_id":run.pk,"status":run.status,
        "material_breaks":run.breaks.filter(material=True).count()},idempotency_key=f"reconciliation:{run.pk}:completed")
    return run
