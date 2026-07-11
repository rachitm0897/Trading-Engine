from apps.reconciliation.services import reconcile
import pytest

pytestmark=pytest.mark.django_db

class FakeGateway:
    def health(self): return {"connected":False,"reconciled":False}
    def positions(self): return []
    def executions(self): return []

def test_disconnected_gateway_creates_material_break():
    run=reconcile("test",FakeGateway())
    assert run.status=="BLOCKED" and run.breaks.filter(material=True).exists()
