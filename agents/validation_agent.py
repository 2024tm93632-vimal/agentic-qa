"""
Validation Agent - Validates generated test code before human review
"""
import ast
import subprocess
import tempfile
import os
from typing import Dict, List


def validate_test(test_code: str) -> Dict[str, any]:
    """
    Validate generated test code for correctness and quality.

    Args:
        test_code: The pytest test code to validate

    Returns:
        Dictionary containing validation results
    """

    result = {
        "is_valid": True,
        "errors": [],
        "warnings": [],
        "test_count": 0
    }

    # Check 1: Is it valid Python syntax?
    try:
        tree = ast.parse(test_code)
    except SyntaxError as e:
        result["is_valid"] = False
        result["errors"].append(f"Syntax error: {str(e)}")
        return result

    # Check 2: Does it contain at least one assertion or pytest.raises?
    if "assert" not in test_code and "pytest.raises" not in test_code:
        result["is_valid"] = False
        result["errors"].append("No assertions found — test would always pass")

    # Check 3: Count test functions and verify naming
    test_functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            test_functions.append(node.name)

    if not test_functions:
        result["is_valid"] = False
        result["errors"].append("No test_ functions found")
    else:
        result["test_count"] = len(test_functions)

    # Check 4: Verify imports
    has_pytest_import = "import pytest" in test_code or "from pytest" in test_code
    if "pytest.raises" in test_code and not has_pytest_import:
        result["warnings"].append("pytest.raises used but pytest not explicitly imported")

    # Check 5: Try to parse with pytest (requires pytest to be installed)
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='_test.py', delete=False) as f:
            f.write(test_code)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                ["python3", "-m", "pytest", "--collect-only", "-q", tmp_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if proc.returncode != 0:
                if "ERROR" in proc.stdout or "ERROR" in proc.stderr:
                    result["errors"].append(f"pytest collection error: {proc.stderr}")
                    result["is_valid"] = False
            else:
                # Parse successful collection output
                if "passed" in proc.stdout or len(test_functions) > 0:
                    result["test_count"] = len(test_functions)
        finally:
            os.unlink(tmp_path)
    except FileNotFoundError:
        result["warnings"].append("pytest not found - cannot validate with pytest")
    except subprocess.TimeoutExpired:
        result["errors"].append("pytest collection timed out")
        result["is_valid"] = False
    except Exception as e:
        result["warnings"].append(f"Could not run pytest validation: {str(e)}")

    # Check 6: Verify test quality heuristics
    lines = test_code.split('\n')
    if len(test_functions) > 0 and len(lines) < 10:
        result["warnings"].append("Tests seem very short - ensure comprehensive coverage")

    return result


def filter_valid_tests(tests: List[str]) -> Dict[str, List[str]]:
    """
    Filter a batch of tests and categorize them.

    Args:
        tests: List of test code strings

    Returns:
        Dictionary with 'valid' and 'invalid' lists
    """

    valid = []
    invalid = []

    for test in tests:
        validation = validate_test(test)
        if validation["is_valid"]:
            valid.append(test)
        else:
            invalid.append({
                "code": test,
                "errors": validation["errors"]
            })

    return {
        "valid": valid,
        "invalid": invalid,
        "valid_count": len(valid),
        "invalid_count": len(invalid)
    }


if __name__ == "__main__":
    # Test with sample valid and invalid tests
    valid_test = """
import pytest

def test_divide_normal():
    result = divide(10, 2)
    assert result == 5

def test_divide_by_zero():
    with pytest.raises(ValueError):
        divide(10, 0)

def test_divide_negative():
    result = divide(-10, 2)
    assert result == -5
"""

    invalid_test = """
def test_divide():
    result = divide(10, 2)
    # No assertion here!
"""

    print("=" * 60)
    print("VALIDATING GOOD TEST")
    print("=" * 60)
    result1 = validate_test(valid_test)
    print(f"Valid: {result1['is_valid']}")
    print(f"Test count: {result1['test_count']}")
    print(f"Errors: {result1['errors']}")
    print(f"Warnings: {result1['warnings']}")

    print("\n" + "=" * 60)
    print("VALIDATING BAD TEST")
    print("=" * 60)
    result2 = validate_test(invalid_test)
    print(f"Valid: {result2['is_valid']}")
    print(f"Test count: {result2['test_count']}")
    print(f"Errors: {result2['errors']}")
