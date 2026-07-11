from apps.reconciliation.services import reconcile
import pytest

pytestmark=pytest.mark.django_db

class FakeGateway:
    def health(self): return {"connected":False,"reconciled":False}
    def positions(self): return []
    def executions(self): return []

class HealthyGateway(FakeGateway):
    def health(self): return {"connected":True,"reconciled":True}

def test_disconnected_gateway_creates_material_break():
    run=reconcile("test",FakeGateway())
    assert run.status=="BLOCKED" and run.breaks.filter(material=True).exists()

def test_clean_run_resolves_prior_transient_gateway_break():
    first=reconcile("disconnect",FakeGateway())
    second=reconcile("recovered",HealthyGateway())
    assert second.status=="COMPLETED"
    assert first.breaks.filter(material=True,resolved=True).exists()
