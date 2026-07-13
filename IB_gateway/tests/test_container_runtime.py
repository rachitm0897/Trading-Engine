from pathlib import Path


def test_entrypoint_stores_the_configured_novnc_password():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    assert 'x11vnc -storepasswd "$novnc_password"' in entrypoint
    assert "| x11vnc -storepasswd -" not in entrypoint
