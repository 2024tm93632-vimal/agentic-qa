"""
Feedback Store - SQLite database for storing test feedback and pending tests
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Tuple
import os
from pathlib import Path

# Anchored to the project root so the CLI and the dashboard share one database
# regardless of the directory they are launched from.
DB_PATH = os.getenv("DATABASE_PATH") or str(Path(__file__).resolve().parent.parent / "feedback.db")

VALID_ACTIONS = ("approve", "modify", "reject")


def init_db():
    """Initialize the SQLite database schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create pending_tests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_tests (
            id TEXT PRIMARY KEY,
            function_code TEXT NOT NULL,
            generated_test TEXT NOT NULL,
            explanation TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Create feedback table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT NOT NULL,
            original_code TEXT NOT NULL,
            corrected_code TEXT,
            action TEXT NOT NULL,
            reason_tag TEXT,
            engineer_id TEXT,
            comments TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (test_id) REFERENCES pending_tests(id)
        )
    """)

    # Create examples table for few-shot learning
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approved_examples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            function_hash TEXT,
            function_code TEXT,
            test_code TEXT,
            approval_count INTEGER DEFAULT 1,
            last_used TEXT,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")


def save_pending_test(test_id: str, function_code: str, generated_test: str, explanation: str = ""):
    """
    Save a pending test that awaits human review.

    Args:
        test_id: Unique identifier for this test
        function_code: The original function code
        generated_test: The generated test code
        explanation: Optional explanation of test coverage
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT OR REPLACE INTO pending_tests
        (id, function_code, generated_test, explanation, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    """, (test_id, function_code, generated_test, explanation, now, now))

    conn.commit()
    conn.close()
    print(f"Saved pending test: {test_id}")


def get_test(test_id: str) -> Dict:
    """Return one test row (any status), or None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM pending_tests WHERE id=?", (test_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_tests(limit: int = None) -> List[Dict]:
    """
    Retrieve all pending tests awaiting review.

    Args:
        limit: Optional limit on number of results

    Returns:
        List of pending test dictionaries
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if limit:
        cursor.execute(
            "SELECT * FROM pending_tests WHERE status='pending' ORDER BY created_at LIMIT ?",
            (limit,)
        )
    else:
        cursor.execute("SELECT * FROM pending_tests WHERE status='pending' ORDER BY created_at")

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def save_feedback(test_id: str, action: str, original_code: str,
                 corrected_code: str = None, reason_tag: str = None,
                 engineer_id: str = "unknown", comments: str = ""):
    """
    Save human feedback on a generated test.

    Args:
        test_id: ID of the test being reviewed
        action: 'approve', 'modify', or 'reject'
        original_code: The original generated test
        corrected_code: If modified, the corrected version
        reason_tag: Tag for why it was rejected/modified (e.g., 'missing_edge_case')
        engineer_id: Email or ID of the engineer giving feedback
        comments: Free-form comments from the engineer
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}, got {action!r}")
    if action == "modify" and not (corrected_code and corrected_code.strip()):
        raise ValueError("modify requires corrected_code")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    status_row = cursor.execute("SELECT status FROM pending_tests WHERE id=?", (test_id,)).fetchone()
    if status_row is None:
        conn.close()
        raise LookupError(f"Unknown test id: {test_id}")
    if status_row[0] != "pending":
        conn.close()
        raise ValueError(f"Test {test_id} was already reviewed ({status_row[0]})")

    now = datetime.now().isoformat()

    # Save feedback
    cursor.execute("""
        INSERT INTO feedback
        (test_id, original_code, corrected_code, action, reason_tag, engineer_id, comments, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (test_id, original_code, corrected_code, action, reason_tag, engineer_id, comments, now))

    # Update test status
    new_status = "approved" if action == "approve" else "modified" if action == "modify" else "rejected"
    cursor.execute(
        "UPDATE pending_tests SET status=?, updated_at=? WHERE id=?",
        (new_status, now, test_id)
    )

    # Approved tests, and engineer-corrected tests, become few-shot examples
    example = original_code if action == "approve" else corrected_code if action == "modify" else None
    if example:
        function_code = cursor.execute(
            "SELECT function_code FROM pending_tests WHERE id=?", (test_id,)).fetchone()[0]
        add_approved_example(function_code, example, conn=conn)

    conn.commit()
    conn.close()
    print(f"Saved feedback for test {test_id}: {action}")


def get_feedback_for_test(test_id: str) -> List[Dict]:
    """
    Get all feedback entries for a specific test.

    Args:
        test_id: The test ID

    Returns:
        List of feedback dictionaries
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM feedback WHERE test_id=? ORDER BY created_at DESC", (test_id,))
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def add_approved_example(function_code: str, test_code: str, conn=None):
    """
    Add an approved test to the examples database for few-shot learning.

    Args:
        function_code: The function being tested
        test_code: The approved test code
    """
    own_conn = conn is None
    if own_conn:
        conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Simple hash of function code
    import hashlib
    func_hash = hashlib.md5(function_code.encode()).hexdigest()[:8]

    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO approved_examples
        (function_hash, function_code, test_code, approval_count, last_used, created_at)
        VALUES (?, ?, ?, 1, ?, ?)
    """, (func_hash, function_code, test_code, now, now))

    if own_conn:
        conn.commit()
        conn.close()


def get_similar_examples(function_code: str, limit: int = 3) -> List[str]:
    """
    Get approved test examples similar to a function (for few-shot learning).

    Args:
        function_code: The function to find similar examples for
        limit: Number of examples to return

    Returns:
        List of approved test code strings
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Very basic: just get most recently approved examples
    cursor.execute("""
        SELECT test_code FROM approved_examples
        ORDER BY approval_count DESC, last_used DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [row[0] for row in rows]


def get_stats() -> Dict:
    """
    Get statistics about the feedback database.

    Returns:
        Dictionary with stats
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    # Count by status
    cursor.execute("""
        SELECT status, COUNT(*) as count FROM pending_tests GROUP BY status
    """)
    for status, count in cursor.fetchall():
        stats[f"tests_{status}"] = count

    # Count feedback by action
    cursor.execute("""
        SELECT action, COUNT(*) as count FROM feedback GROUP BY action
    """)
    for action, count in cursor.fetchall():
        stats[f"feedback_{action}"] = count

    # Approval rate
    cursor.execute("SELECT COUNT(*) FROM feedback WHERE action='approve'")
    approved = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM feedback")
    total = cursor.fetchone()[0]
    if total > 0:
        stats["approval_rate"] = approved / total

    conn.close()
    return stats


if __name__ == "__main__":
    init_db()
    print("\nDatabase schema created successfully!")
    print(f"Database location: {DB_PATH}")
