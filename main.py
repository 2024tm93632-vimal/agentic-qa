#!/usr/bin/env python3
"""
Agentic QA - Main CLI entry point
Orchestrates code analysis, test generation, validation, and feedback collection
"""
import sys
import argparse
import uuid
from pathlib import Path

# Add agents to path
sys.path.insert(0, str(Path(__file__).parent))

from agents.test_generation_agent import generate_tests, generate_tests_for_change, build_change_prompt
from agents.change_analysis_agent import analyze_commit, _functions, GitError
from agents.code_analysis_agent import analyze_function, build_enriched_prompt
from agents.validation_agent import validate_test
from feedback.feedback_store import (
    init_db, save_pending_test, get_pending_tests,
    save_feedback, get_similar_examples, get_stats, get_test
)


def generate_from_file(file_path: str) -> None:
    """
    Generate tests for all functions in a Python file.

    Args:
        file_path: Path to Python file to analyze
    """
    print(f"\n📂 Reading file: {file_path}")

    try:
        with open(file_path, 'r') as f:
            code = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return

    # Analyze code
    print("\n🔍 Analyzing code structure...")
    analysis = analyze_function(code)

    if analysis.get("error"):
        print(f"❌ Analysis error: {analysis['error']}")
        return

    functions = analysis.get("functions", [])
    if not functions:
        print("⚠️  No functions found in file")
        return

    print(f"✓ Found {len(functions)} function(s)")

    # Get few-shot examples
    print("\n📚 Retrieving similar approved examples...")
    few_shot_examples = get_similar_examples(code, limit=2)
    if few_shot_examples:
        print(f"✓ Found {len(few_shot_examples)} similar examples")

    # Generate tests for each function
    for func in functions:
        func_name = func['name']
        func_code = next((src for qual, (_, src) in _functions(code).items()
                          if qual.split(".")[-1] == func_name), code)

        print(f"\n{'='*60}")
        print(f"🧪 Generating tests for: {func_name}()")
        print(f"{'='*60}")

        # Build enriched prompt
        prompt = build_enriched_prompt(func_code, few_shot_examples)

        # Generate tests
        print("⏳ Calling LLM to generate tests...")
        generated_test = generate_tests(func_code, prompt=prompt)

        # Validate generated test
        print("✓ Validating generated test...")
        validation = validate_test(generated_test)

        if not validation["is_valid"]:
            print(f"❌ Validation failed:")
            for error in validation["errors"]:
                print(f"   - {error}")
            continue

        print(f"✓ Validation passed ({validation['test_count']} test functions)")

        # Save to pending review
        test_id = f"{func_name}_{uuid.uuid4().hex[:8]}"
        save_pending_test(
            test_id=test_id,
            function_code=func_code,
            generated_test=generated_test,
            explanation=f"Auto-generated tests for {func_name}"
        )

        print(f"\n📌 Test ID: {test_id}")
        print("💾 Saved to pending review")

        # Show preview
        print("\n📋 Test Preview:")
        print("-" * 40)
        lines = generated_test.split("\n")
        print("\n".join(lines[:15]))
        if len(lines) > 15:
            print(f"\n... ({len(lines) - 15} more lines)")


def generate_from_code(code_snippet: str) -> None:
    """
    Generate tests for a code snippet provided as string.

    Args:
        code_snippet: Python code as string
    """
    print("\n📝 Analyzing provided code snippet...")

    # Analyze
    analysis = analyze_function(code_snippet)

    if analysis.get("error"):
        print(f"❌ Analysis error: {analysis['error']}")
        return

    functions = analysis.get("functions", [])
    if not functions:
        print("⚠️  No functions found")
        return

    print(f"✓ Found {len(functions)} function(s)")

    # Generate tests
    print("\n🧪 Generating tests...")
    print("⏳ Calling LLM...")
    generated_test = generate_tests(code_snippet, prompt=build_enriched_prompt(code_snippet))

    # Validate
    print("✓ Validating...")
    validation = validate_test(generated_test)

    if not validation["is_valid"]:
        print(f"❌ Validation failed:")
        for error in validation["errors"]:
            print(f"   - {error}")
        return

    print(f"✓ Valid ({validation['test_count']} test functions)")

    # Save
    test_id = f"test_{uuid.uuid4().hex[:12]}"
    save_pending_test(
        test_id=test_id,
        function_code=code_snippet,
        generated_test=generated_test
    )

    print(f"\n✅ Generated Test (ID: {test_id})")
    print("=" * 60)
    print(generated_test)
    print("=" * 60)


def generate_from_commit(rev: str, base: str, repo: str, dry_run: bool) -> None:
    """Generate tests only for functions changed by a commit (or base..rev range)."""
    try:
        changes = analyze_commit(repo, rev, base)
    except GitError as e:
        print(f"❌ Git error: {e}")
        return

    print(f"\n🔎 {rev}: {len(changes)} changed function(s)")
    for c in changes:
        print(f"   [{c.kind}] {c.file}::{c.qualname}")

    stale = [c for c in changes if c.kind == "removed" and c.existing_tests]
    for c in stale:
        print(f"⚠️  {c.qualname} was removed but {len(c.existing_tests)} test(s) still reference it")

    targets = [c for c in changes if c.needs_tests]
    if not targets:
        print("✓ Nothing to generate")
        return

    for change in targets:
        print(f"\n{'='*60}\n🧪 {change.kind}: {change.qualname}\n{'='*60}")
        if dry_run:
            print(build_change_prompt(change))
            continue

        try:
            generated_test = generate_tests_for_change(change, few_shot_examples=get_similar_examples(change.new_source, limit=2))
        except Exception as e:
            print(f"❌ LLM call failed: {e}")
            continue

        validation = validate_test(generated_test)
        if not validation["is_valid"]:
            print("❌ Validation failed:")
            for error in validation["errors"]:
                print(f"   - {error}")
            continue

        test_id = f"{change.qualname.replace('.', '_')}_{uuid.uuid4().hex[:8]}"
        save_pending_test(
            test_id=test_id,
            function_code=change.new_source,
            generated_test=generated_test,
            explanation=f"{change.kind} in {rev}: {change.file}::{change.qualname}",
        )
        print(f"✓ {validation['test_count']} test(s) saved to pending review (ID: {test_id})")


def review_pending() -> None:
    """List pending tests with a preview and the commands to act on them."""
    pending = get_pending_tests()
    print(f"\n📋 {len(pending)} pending test(s)")
    for test in pending:
        print(f"\n{'='*60}\nID: {test['id']}  ({test['created_at'][:19]})")
        if test.get("explanation"):
            print(test["explanation"])
        lines = test["generated_test"].splitlines()
        print("-" * 40)
        print("\n".join(lines[:12]))
        if len(lines) > 12:
            print(f"... ({len(lines) - 12} more lines)")
        print(f"\n  approve: python main.py approve {test['id']}")
        print(f"  reject:  python main.py reject {test['id']} --reason missing_edge_case")
        print(f"  modify:  python main.py modify {test['id']} corrected_test.py")
    if pending:
        print("\nOr review in the browser: python -m dashboard.backend.app")


def record_feedback(test_id: str, action: str, corrected_file: str = None,
                    reason: str = None, comment: str = "", engineer: str = "cli") -> None:
    test = get_test(test_id)
    if test is None:
        print(f"❌ Unknown test id: {test_id}")
        return
    corrected = None
    if corrected_file:
        try:
            corrected = Path(corrected_file).read_text()
        except OSError as e:
            print(f"❌ Cannot read {corrected_file}: {e}")
            return
        check = validate_test(corrected)
        if not check["is_valid"]:
            print("❌ Corrected test is not valid:")
            for error in check["errors"]:
                print(f"   - {error}")
            return
    try:
        save_feedback(test_id, action, test["generated_test"], corrected_code=corrected,
                      reason_tag=reason, engineer_id=engineer, comments=comment)
    except (ValueError, LookupError) as e:
        print(f"❌ {e}")


def show_stats() -> None:
    """Display database statistics."""
    print("\n📊 Feedback Statistics")
    print("=" * 60)

    stats = get_stats()

    if not stats:
        print("No statistics available yet")
        return

    for key, value in stats.items():
        if isinstance(value, float):
            print(f"{key}: {value:.1%}")
        else:
            print(f"{key}: {value}")


def main():
    parser = argparse.ArgumentParser(
        description="Agentic QA - AI-powered test generation"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Generate from file
    gen_file = subparsers.add_parser("generate", help="Generate tests from Python file")
    gen_file.add_argument("file", help="Python file path")

    # Generate from snippet
    snippet = subparsers.add_parser("snippet", help="Generate tests from code snippet")
    snippet.add_argument("code", help="Python code snippet")

    # Generate from commit
    commit = subparsers.add_parser("from-commit", help="Generate tests for functions changed in a commit")
    commit.add_argument("rev", nargs="?", default="HEAD", help="Commit to analyse (default: HEAD)")
    commit.add_argument("--base", help="Compare against this commit instead of the parent")
    commit.add_argument("--repo", default=".", help="Git repository path (default: .)")
    commit.add_argument("--dry-run", action="store_true", help="Print prompts without calling the LLM")

    # Review pending
    subparsers.add_parser("review", help="List pending tests")

    for name, text in (("approve", "Approve a pending test"), ("reject", "Reject a pending test"),
                       ("modify", "Replace a pending test with a corrected version")):
        sp = subparsers.add_parser(name, help=text)
        sp.add_argument("test_id")
        if name == "modify":
            sp.add_argument("file", help="File containing the corrected test")
        if name != "approve":
            sp.add_argument("--reason", help="Tag, e.g. missing_edge_case, wrong_assertion")
        sp.add_argument("--comment", default="")
        sp.add_argument("--engineer", default="cli")

    # Statistics
    subparsers.add_parser("stats", help="Show feedback statistics")

    # Initialize
    subparsers.add_parser("init", help="Initialize database")

    args = parser.parse_args()

    # Initialize DB if needed
    if args.command != "init":
        try:
            init_db()
        except:
            pass

    if args.command == "generate":
        generate_from_file(args.file)
    elif args.command == "snippet":
        generate_from_code(args.code)
    elif args.command == "from-commit":
        generate_from_commit(args.rev, args.base, args.repo, args.dry_run)
    elif args.command in ("approve", "reject", "modify"):
        record_feedback(args.test_id, args.command, getattr(args, "file", None),
                        getattr(args, "reason", None), args.comment, args.engineer)
    elif args.command == "review":
        review_pending()
    elif args.command == "stats":
        show_stats()
    elif args.command == "init":
        init_db()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
