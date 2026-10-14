"""The public demo page uses generated data; it must match the real flows and hold nothing private."""
from __future__ import annotations

from app.demo_data import OUT, render


def test_demo_data_is_up_to_date():
    assert OUT.read_text(encoding="utf-8") == render(), "run: cd pc1-orchestrator && python -m app.demo_data"


def test_demo_data_has_no_private_names():
    text = render().lower()
    for private in ("panud", "kingfluk", "flukelnwza", "portfolio", "tdee", "webecommerce", "192.168."):
        assert private not in text


def test_demo_page_needs_no_sign_in_but_the_api_still_does(rig, tmp_path):
    from fastapi.testclient import TestClient

    from app.adapters.notify import Broadcaster
    from app.api.app import create_app
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(rig.orch, rig.store, Broadcaster(), static_dir=tmp_path)) as c:
        r = c.get("/demo")
        assert r.status_code == 200 and "app" in r.text
        assert c.get("/jobs").status_code == 401 and c.get("/flows").status_code == 401
