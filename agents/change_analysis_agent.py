"""
Change Analysis Agent - turns a git commit (or range) into the list of functions
that actually changed, so tests are generated only for what the commit touched.

Changes are detected by comparing the old and new ASTs of each function, so
comment-only and formatting-only edits are ignored.
"""
import ast
import difflib
import subprocess
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from .code_analysis_agent import describe_function

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_TEST_PATTERNS = ("*test_*.py", "*_test.py")


class GitError(Exception):
    pass


@dataclass
class FunctionChange:
    file: str
    qualname: str
    kind: str  # added | modified | signature_changed | removed
    new_source: str = ""
    old_source: str = ""
    diff: str = ""
    analysis: Dict = field(default_factory=dict)
    existing_tests: List[str] = field(default_factory=list)

    @property
    def module(self) -> str:
        return self.file[:-3].replace("/", ".") if self.file.endswith(".py") else self.file

    @property
    def needs_tests(self) -> bool:
        return self.kind != "removed"


def _git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _show(repo: str, rev: str, path: str) -> Optional[str]:
    try:
        return _git(repo, "show", f"{rev}:{path}")
    except GitError:
        return None


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}"


def _functions(source: Optional[str]) -> Dict[str, Tuple[ast.AST, str]]:
    """Map qualname -> (node, source segment) for module-level functions and class methods."""
    if not source:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: Dict[str, Tuple[ast.AST, str]] = {}

    def visit(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + node.name] = (node, ast.get_source_segment(source, node) or "")
            elif isinstance(node, ast.ClassDef):
                visit(node.body, f"{prefix}{node.name}.")

    visit(tree.body, "")
    return found


def _signature(node: ast.AST) -> str:
    return ast.dump(node.args) + ast.dump(node.returns) if node.returns else ast.dump(node.args)


def _existing_tests(repo: str, rev: str, name: str) -> List[str]:
    """Source of test functions at `rev` whose body mentions the function's short name."""
    short = name.rsplit(".", 1)[-1]
    try:
        files = _git(repo, "grep", "-l", "-w", short, rev, "--", *_TEST_PATTERNS).splitlines()
    except GitError:
        return []
    found = []
    for entry in files:
        path = entry.split(":", 1)[1] if ":" in entry else entry
        for qual, (node, src) in _functions(_show(repo, rev, path)).items():
            if qual.split(".")[-1].startswith("test_") and short in src:
                found.append(src)
    return found


def diff_functions(path: str, old: Optional[str], new: Optional[str]) -> List[FunctionChange]:
    """Compare two versions of one file and return per-function changes."""
    old_fns, new_fns = _functions(old), _functions(new)
    changes: List[FunctionChange] = []

    for qual, (node, src) in new_fns.items():
        if qual not in old_fns:
            changes.append(FunctionChange(path, qual, "added", new_source=src,
                                          analysis=describe_function(node)))
            continue
        old_node, old_src = old_fns[qual]
        if ast.dump(old_node) == ast.dump(node):
            continue
        kind = "signature_changed" if _signature(old_node) != _signature(node) else "modified"
        udiff = "\n".join(difflib.unified_diff(
            old_src.splitlines(), src.splitlines(), "before", "after", lineterm="", n=2))
        changes.append(FunctionChange(path, qual, kind, new_source=src, old_source=old_src,
                                      diff=udiff, analysis=describe_function(node)))

    for qual, (node, src) in old_fns.items():
        if qual not in new_fns:
            changes.append(FunctionChange(path, qual, "removed", old_source=src))
    return changes


def analyze_commit(repo: str = ".", rev: str = "HEAD", base: Optional[str] = None) -> List[FunctionChange]:
    """Functions changed between `base` and `rev` (default: the commit's first parent).

    Test files are excluded. Each non-removed change carries the existing tests that
    mention it; removed functions carry the tests that now reference nothing.
    """
    if base is None:
        try:
            base = _git(repo, "rev-parse", "--verify", "-q", f"{rev}^").strip()
        except GitError:
            base = EMPTY_TREE

    changes: List[FunctionChange] = []
    for line in _git(repo, "diff", "--name-status", "--no-renames", base, rev, "--", "*.py").splitlines():
        status, path = line.split("\t", 1)
        if _is_test_file(path):
            continue
        old = _show(repo, base, path) if status != "A" else None
        new = _show(repo, rev, path) if status != "D" else None
        for change in diff_functions(path, old, new):
            lookup_rev = base if change.kind == "removed" else rev
            change.existing_tests = _existing_tests(repo, lookup_rev, change.qualname)
            changes.append(change)
    return changes
