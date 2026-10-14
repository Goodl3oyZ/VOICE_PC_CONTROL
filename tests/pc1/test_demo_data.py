"""The public demo page uses generated data; it must match the real flows and hold nothing private."""
from __future__ import annotations

from app.demo_data import OUT, render


def test_demo_data_is_up_to_date():
    assert OUT.read_text(encoding="utf-8") == render(), "run: cd pc1-orchestrator && python -m app.demo_data"


def test_demo_data_has_no_private_names():
    """Only the generic knowledge file and the made-up PC: no real user folders, hosts or found projects."""
    import re
    text = render()
    assert set(re.findall(r"C:\\Users\\([^\\]+)", text)) <= {"you"}
    assert not re.search(r"(?:10|192\.168|100)\.\d+\.\d+", text)
    assert "my-website" in text and ".online" not in text


def test_demo_page_needs_no_sign_in_but_the_api_still_does(rig, tmp_path):
    from fastapi.testclient import TestClient

    from app.adapters.notify import Broadcaster
    from app.api.app import create_app
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(rig.orch, rig.store, Broadcaster(), static_dir=tmp_path)) as c:
        r = c.get("/demo")
        assert r.status_code == 200 and "app" in r.text
        assert c.get("/jobs").status_code == 401 and c.get("/flows").status_code == 401
