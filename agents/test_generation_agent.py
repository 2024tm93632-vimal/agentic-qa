"""
Test Generation Agent - builds prompts from code changes and asks an LLM for pytest tests.

The LLM is a plain callable (prompt -> text) so the agent can be tested offline.
"""
import os
import re
from pathlib import Path
from typing import Callable, List, Optional

from .change_analysis_agent import FunctionChange

LLM = Callable[[str], str]

_FENCE = re.compile(r"^```[a-zA-Z]*\n|\n?```\s*$")

_KIND_GUIDANCE = {
    "added": "This function is NEW. Cover the happy path, edge cases, boundaries and every raised exception.",
    "modified": (
        "This function was MODIFIED in the commit. Focus on the behaviour that the diff changes "
        "(both the new behaviour and inputs where old and new behaviour differ), then add regression "
        "tests for the unchanged behaviour. Do not duplicate cases already covered by the existing tests."
    ),
    "signature_changed": (
        "This function's SIGNATURE changed. Test the new signature (new/renamed/removed parameters, "
        "defaults, return type) and verify the behaviour still matches the docstring."
    ),
}


def gemini_llm(prompt: str) -> str:
    """Default LLM: Google Gemini via the google-genai SDK (needs GEMINI_API_KEY)."""
    from dotenv import load_dotenv
    from google import genai

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.getenv("GEMINI_API_KEY")
    if not key or key == "your_api_key_here":
        raise RuntimeError("Set GEMINI_API_KEY in .env")
    client = genai.Client(api_key=key)
    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    return client.models.generate_content(model=model, contents=prompt).text or ""


def clean_llm_output(text: str) -> str:
    """Strip markdown fences that LLMs add despite being told not to."""
    return _FENCE.sub("", text.strip()).strip() + "\n"


def build_change_prompt(change: FunctionChange, few_shot_examples: Optional[List[str]] = None) -> str:
    a = change.analysis
    args = ", ".join(f"{x['name']}: {x['type']}" if x["type"] else x["name"] for x in a.get("args", []))
    sections = [
        "You are an expert QA engineer writing pytest tests for a code change in a Python project.",
        f"## CHANGE\nFile: {change.file}\nFunction: {change.qualname}\nKind: {change.kind}\n"
        f"{_KIND_GUIDANCE.get(change.kind, '')}",
        f"## FUNCTION (current version)\n```python\n{change.new_source}\n```",
        f"## ANALYSIS\nSignature: {change.qualname.rsplit('.', 1)[-1]}({args})\n"
        f"Returns: {a.get('returns') or 'unannotated'}\n"
        f"Raises: {', '.join(a.get('raises', [])) or 'nothing explicit'}",
    ]
    if change.diff:
        sections.append(f"## DIFF (before -> after)\n```diff\n{change.diff}\n```")
    if change.existing_tests:
        sections.append("## EXISTING TESTS (do not duplicate; keep consistent style)\n"
                        + "\n\n".join(f"```python\n{t}\n```" for t in change.existing_tests))
    if few_shot_examples:
        sections.append("## APPROVED EXAMPLES FROM THIS PROJECT\n"
                        + "\n---\n".join(few_shot_examples))
    sections.append(
        "## OUTPUT RULES\n"
        f"- Import the code under test with: from {change.module} import "
        f"{change.qualname.split('.')[0]}\n"
        "- Output ONLY runnable pytest code: no markdown fences, no explanations\n"
        "- Every test function starts with test_ and contains real assertions\n"
        "- Use pytest.raises for exceptions; use tmp_path for any files"
    )
    return "\n\n".join(sections)


def generate_tests_for_change(change: FunctionChange, llm: Optional[LLM] = None,
                              few_shot_examples: Optional[List[str]] = None) -> str:
    if not change.needs_tests:
        raise ValueError(f"{change.qualname} was removed; nothing to generate")
    return clean_llm_output((llm or gemini_llm)(build_change_prompt(change, few_shot_examples)))


def generate_tests(function_code: str, prompt: Optional[str] = None, llm: Optional[LLM] = None) -> str:
    """Snippet/file mode: generate tests from raw code, or from a prebuilt prompt."""
    if prompt is None:
        from .code_analysis_agent import build_enriched_prompt
        prompt = build_enriched_prompt(function_code)
    return clean_llm_output((llm or gemini_llm)(prompt))
