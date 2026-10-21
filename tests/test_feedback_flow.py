import pytest
from fastapi.testclient import TestClient

from agents.change_analysis_agent import FunctionChange
from agents.test_generation_agent import build_change_prompt
from dashboard.backend.app import app
from feedback import feedback_store as store

GOOD_TEST = "import pytest\n\ndef test_ok():\n    assert 1 + 1 == 2\n"
EDITED_TEST = "def test_edited():\n    assert 2 + 2 == 4\n"


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "fb.db"))
    store.init_db()


@pytest.fixture
def pending():
    store.save_pending_test("t1", "def f(): return 1", GOOD_TEST, "modified in abc123")
    return "t1"


def test_approve_creates_example_and_updates_stats(pending):
    store.save_feedback(pending, "approve", GOOD_TEST)
    assert store.get_test(pending)["status"] == "approved"
    assert store.get_similar_examples("anything") == [GOOD_TEST]
    assert store.get_stats()["approval_rate"] == 1.0


def test_modify_stores_the_corrected_test_not_the_original(pending):
    store.save_feedback(pending, "modify", GOOD_TEST, corrected_code=EDITED_TEST, reason_tag="wrong_assertion")
    assert store.get_test(pending)["status"] == "modified"
    assert store.get_similar_examples("x") == [EDITED_TEST]


def test_reject_does_not_create_example(pending):
    store.save_feedback(pending, "reject", GOOD_TEST, reason_tag="not_runnable")
    assert store.get_test(pending)["status"] == "rejected"
    assert store.get_similar_examples("x") == []


def test_cannot_review_twice(pending):
    store.save_feedback(pending, "approve", GOOD_TEST)
    with pytest.raises(ValueError):
        store.save_feedback(pending, "approve", GOOD_TEST)
    assert len(store.get_similar_examples("x", limit=10)) == 1


def test_invalid_inputs_rejected(pending):
    with pytest.raises(ValueError):
        store.save_feedback(pending, "bogus", GOOD_TEST)
    with pytest.raises(ValueError):
        store.save_feedback(pending, "modify", GOOD_TEST)
    with pytest.raises(LookupError):
        store.save_feedback("missing", "approve", GOOD_TEST)
    assert store.get_test(pending)["status"] == "pending"


def test_approved_example_appears_in_next_generation_prompt(pending):
    store.save_feedback(pending, "approve", GOOD_TEST)
    change = FunctionChange("a.py", "g", "added", new_source="def g(): pass", analysis={"args": []})
    prompt = build_change_prompt(change, store.get_similar_examples(change.new_source))
    assert "def test_ok" in prompt
    assert "def test_ok" not in build_change_prompt(change)


client = TestClient(app)


def test_api_list_and_detail(pending):
    assert [t["id"] for t in client.get("/api/tests").json()] == ["t1"]
    detail = client.get("/api/tests/t1").json()
    assert detail["generated_test"] == GOOD_TEST and detail["feedback"] == []
    assert client.get("/api/tests/nope").status_code == 404
    assert client.get("/api/tests?status=bogus").status_code == 422


def test_api_approve_then_conflict(pending):
    r = client.post("/api/tests/t1/feedback", json={"action": "approve"})
    assert r.status_code == 200 and r.json()["stats"]["tests_approved"] == 1
    assert client.post("/api/tests/t1/feedback", json={"action": "approve"}).status_code == 409
    assert client.get("/api/tests").json() == []
    assert client.get("/api/tests?status=approved").json()[0]["id"] == "t1"


def test_api_modify_validates_corrected_code(pending):
    assert client.post("/api/tests/t1/feedback", json={"action": "modify"}).status_code == 422
    bad = client.post("/api/tests/t1/feedback", json={"action": "modify", "corrected_code": "def broken(:"})
    assert bad.status_code == 422 and "not valid" in bad.json()["detail"]
    ok = client.post("/api/tests/t1/feedback", json={"action": "modify", "corrected_code": EDITED_TEST})
    assert ok.status_code == 200
    assert store.get_similar_examples("x") == [EDITED_TEST]


def test_api_reject_unknown_and_bad_action(pending):
    assert client.post("/api/tests/nope/feedback", json={"action": "reject"}).status_code == 404
    assert client.post("/api/tests/t1/feedback", json={"action": "bogus"}).status_code == 422
    r = client.post("/api/tests/t1/feedback", json={"action": "reject", "reason_tag": "not_runnable", "comments": "x"})
    assert r.status_code == 200 and client.get("/api/tests/t1").json()["feedback"][0]["reason_tag"] == "not_runnable"


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "Agentic QA Review" in r.text
