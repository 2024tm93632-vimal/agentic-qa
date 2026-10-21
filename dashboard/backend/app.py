"""Review dashboard API: list generated tests and record approve / modify / reject feedback."""
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.validation_agent import validate_test
from feedback import feedback_store as store

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
STATUSES = ("pending", "approved", "modified", "rejected")

app = FastAPI(title="Agentic QA Review")


class FeedbackIn(BaseModel):
    action: str
    corrected_code: Optional[str] = None
    reason_tag: Optional[str] = None
    comments: str = ""
    engineer_id: str = "dashboard"


def _query(status: str):
    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM pending_tests WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/tests")
def list_tests(status: str = "pending"):
    if status not in STATUSES:
        raise HTTPException(422, f"status must be one of {STATUSES}")
    return [{k: t[k] for k in ("id", "status", "explanation", "created_at")} for t in _query(status)]


@app.get("/api/tests/{test_id}")
def get_test(test_id: str):
    test = store.get_test(test_id)
    if test is None:
        raise HTTPException(404, "Unknown test id")
    test["feedback"] = store.get_feedback_for_test(test_id)
    return test


@app.post("/api/tests/{test_id}/feedback")
def post_feedback(test_id: str, body: FeedbackIn):
    test = store.get_test(test_id)
    if test is None:
        raise HTTPException(404, "Unknown test id")
    if test["status"] != "pending":
        raise HTTPException(409, f"Already reviewed ({test['status']})")
    if body.action not in store.VALID_ACTIONS:
        raise HTTPException(422, f"action must be one of {store.VALID_ACTIONS}")
    if body.action == "modify":
        if not (body.corrected_code or "").strip():
            raise HTTPException(422, "modify requires corrected_code")
        check = validate_test(body.corrected_code)
        if not check["is_valid"]:
            raise HTTPException(422, "Corrected test is not valid: " + "; ".join(check["errors"]))
    store.save_feedback(test_id, body.action, test["generated_test"], corrected_code=body.corrected_code,
                        reason_tag=body.reason_tag, engineer_id=body.engineer_id, comments=body.comments)
    return {"ok": True, "stats": store.get_stats()}


@app.get("/api/stats")
def stats():
    return store.get_stats()


@app.get("/")
def index():
    return FileResponse(FRONTEND)


if __name__ == "__main__":
    import uvicorn
    store.init_db()
    uvicorn.run(app, host="127.0.0.1", port=8000)
