import subprocess
import textwrap

import pytest

from agents.change_analysis_agent import analyze_commit, diff_functions
from agents.test_generation_agent import (build_change_prompt, clean_llm_output,
                                          generate_tests_for_change)


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def commit(repo, files, msg):
    for name, body in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    commit(tmp_path, {
        "pkg/mod.py": '''
            def keep(x):
                return x

            def tweak(x):
                return x + 1

            def resig(a):
                return a

            def gone():
                return 1
        ''',
        "tests/test_mod.py": '''
            from pkg.mod import tweak, gone

            def test_tweak():
                assert tweak(1) == 2

            def test_gone():
                assert gone() == 1
        ''',
    }, "initial")
    return tmp_path


def by_name(changes):
    return {c.qualname: c for c in changes}


def test_initial_commit_everything_is_added(repo):
    changes = by_name(analyze_commit(str(repo)))
    assert {c.kind for c in changes.values()} == {"added"}
    assert set(changes) == {"keep", "tweak", "resig", "gone"}


def test_classifies_modified_signature_added_removed(repo):
    commit(repo, {"pkg/mod.py": '''
        def keep(x):
            return x

        def tweak(x):
            return x + 2

        def resig(a, b=0):
            return a + b

        def fresh():
            return 3
    '''}, "change things")
    changes = by_name(analyze_commit(str(repo)))
    assert {n: c.kind for n, c in changes.items()} == {
        "tweak": "modified", "resig": "signature_changed", "fresh": "added", "gone": "removed"}
    assert "-    return x + 1" in changes["tweak"].diff
    assert "+    return x + 2" in changes["tweak"].diff


def test_existing_tests_attached_and_stale_tests_flagged(repo):
    commit(repo, {"pkg/mod.py": '''
        def keep(x):
            return x

        def tweak(x):
            return x + 2

        def resig(a):
            return a
    '''}, "drop gone, edit tweak")
    changes = by_name(analyze_commit(str(repo)))
    assert any("def test_tweak" in t for t in changes["tweak"].existing_tests)
    assert changes["gone"].kind == "removed"
    assert any("def test_gone" in t for t in changes["gone"].existing_tests)


def test_comment_and_formatting_only_changes_are_ignored(repo):
    commit(repo, {"pkg/mod.py": '''
        def keep(x):
            # now with a comment
            return   x

        def tweak(x):
            return x+1

        def resig(a):
            return a

        def gone():
            return 1
    '''}, "cosmetic")
    assert analyze_commit(str(repo)) == []


def test_test_files_and_non_python_are_skipped(repo):
    commit(repo, {"tests/test_mod.py": "def test_new():\n    assert True\n", "README.md": "hi"}, "tests only")
    assert analyze_commit(str(repo)) == []


def test_methods_get_qualified_names():
    old = "class A:\n    def m(self):\n        return 1\n"
    new = "class A:\n    def m(self):\n        return 2\n"
    (change,) = diff_functions("a.py", old, new)
    assert change.qualname == "A.m" and change.kind == "modified"


def test_explicit_base_range_covers_multiple_commits(repo):
    commit(repo, {"pkg/mod.py": "def keep(x):\n    return x * 2\n"}, "one")
    commit(repo, {"pkg/extra.py": "def extra():\n    return 1\n"}, "two")
    names = {c.qualname for c in analyze_commit(str(repo), "HEAD", base="HEAD~2")}
    assert {"keep", "extra"} <= names


def test_bad_revision_raises(repo):
    from agents.change_analysis_agent import GitError
    with pytest.raises(GitError):
        analyze_commit(str(repo), "does-not-exist")


def test_prompt_contains_diff_existing_tests_and_import(repo):
    commit(repo, {"pkg/mod.py": "def tweak(x):\n    return x + 2\n"}, "edit")
    change = by_name(analyze_commit(str(repo)))["tweak"]
    prompt = build_change_prompt(change)
    assert "MODIFIED" in prompt
    assert "+    return x + 2" in prompt
    assert "def test_tweak" in prompt
    assert "from pkg.mod import tweak" in prompt


def test_generate_uses_llm_and_strips_fences(repo):
    change = by_name(analyze_commit(str(repo)))["tweak"]
    seen = []

    def fake_llm(prompt):
        seen.append(prompt)
        return "```python\ndef test_x():\n    assert True\n```"

    out = generate_tests_for_change(change, llm=fake_llm)
    assert out == "def test_x():\n    assert True\n"
    assert "tweak" in seen[0]


def test_generate_refuses_removed_functions(repo):
    commit(repo, {"pkg/mod.py": "def keep(x):\n    return x\n"}, "drop rest")
    removed = by_name(analyze_commit(str(repo)))["gone"]
    with pytest.raises(ValueError):
        generate_tests_for_change(removed, llm=lambda p: "")


def test_clean_llm_output_leaves_plain_code_alone():
    assert clean_llm_output("def test_a():\n    assert 1\n") == "def test_a():\n    assert 1\n"
