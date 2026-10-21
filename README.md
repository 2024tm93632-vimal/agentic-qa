# Agentic Test Generation: LLMs with Human Feedback

Generates pytest tests for the functions a git commit changed, lets an engineer approve,
edit or reject them, and feeds approved tests back into later prompts as few-shot examples.

BITS Pilani dissertation project (BITS ZG628T).

## Setup

```bash
conda activate agentic-qa
pip install -r requirements.txt
cp .env.example .env   # then set GEMINI_API_KEY (free key: aistudio.google.com/apikey)
```

Optional `.env` settings: `GEMINI_MODEL` (default `gemini-flash-latest`), `DATABASE_PATH`.

## Usage

```bash
# Tests for the functions changed in a commit (or a range)
python main.py from-commit HEAD --repo /path/to/repo
python main.py from-commit HEAD --base main --repo /path/to/repo --dry-run   # print prompts only

# Review generated tests in the browser (http://127.0.0.1:8000)
python -m dashboard.backend.app

# ...or from the CLI
python main.py review
python main.py approve <id>
python main.py reject <id> --reason missing_edge_case
python main.py modify <id> corrected_test.py

# Whole-file / snippet modes, and stats
python main.py generate sample_code/math_utils.py
python main.py snippet "def f(x): return x"
python main.py stats
```

Generated tests import the code under test by its module path, so run them from the target repo's root.

## How it works

```
git commit ──► change_analysis_agent ──► test_generation_agent ──► validation_agent ──► pending (SQLite)
               (which functions changed,   (prompt = function + diff   (syntax, test_ funcs,        │
                via old/new AST diff)       + existing tests            assertions, pytest          ▼
                                            + approved examples)        collection)          review: dashboard / CLI
                                                  ▲                                                  │
                                                  └──────── approved / corrected tests ◄─────────────┘
```

- **Change analysis** (`agents/change_analysis_agent.py`) compares old and new ASTs per function, classifying
  each as `added`, `modified`, `signature_changed` or `removed`. Comment-only and formatting-only changes are ignored.
- **Generation** (`agents/test_generation_agent.py`) builds a prompt tailored to the kind of change. The LLM
  is a plain callable, so the agent can be tested offline.
- **Feedback** (`feedback/feedback_store.py`): approving stores the test as a few-shot example; modifying stores
  the engineer's corrected version. Example selection is currently "most recently approved"; similarity search
  via a vector DB is planned.
- **`pdf_extract/`** is the sample feature under test: PDF text/table/metadata extraction and invoice field parsing.

## Layout

```
agents/       change analysis, test generation, validation
feedback/     SQLite store (pending tests, feedback, approved examples)
dashboard/    FastAPI backend + single-page review UI (no build step)
pdf_extract/  sample feature
tests/        pytest suite (git repos and PDFs are built in temp dirs; no network)
main.py       CLI
```

## Tests

```bash
python -m pytest tests -q
```

## Status

| Piece | State |
|---|---|
| Commit-driven analysis and generation | working (verified with a real Gemini run) |
| Validation, feedback store, CLI approval | working |
| Review dashboard | working; no authentication, localhost only |
| Similarity-based few-shot selection (ChromaDB) | not started |
| Groq / OpenAI backends | not wired (Gemini only) |
| CI/CD (GitHub Actions) | not started |
