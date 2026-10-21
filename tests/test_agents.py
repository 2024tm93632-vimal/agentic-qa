"""
Unit tests for the agentic-qa agents
"""
import pytest
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.code_analysis_agent import analyze_function
from agents.validation_agent import validate_test


class TestCodeAnalysis:
    """Tests for the code analysis agent"""

    def test_analyze_simple_function(self):
        """Test analyzing a simple function"""
        code = """
def hello(name: str) -> str:
    return f"Hello, {name}!"
"""
        analysis = analyze_function(code)
        assert len(analysis["functions"]) == 1
        assert analysis["functions"][0]["name"] == "hello"
        assert len(analysis["functions"][0]["args"]) == 1

    def test_analyze_function_with_exceptions(self):
        """Test analyzing function that raises exceptions"""
        code = """
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
"""
        analysis = analyze_function(code)
        assert len(analysis["functions"]) == 1
        func = analysis["functions"][0]
        assert "ValueError" in func["raises"]

    def test_analyze_multiple_functions(self):
        """Test analyzing code with multiple functions"""
        code = """
def func1():
    pass

def func2():
    pass

def func3():
    pass
"""
        analysis = analyze_function(code)
        assert len(analysis["functions"]) == 3

    def test_analyze_syntax_error(self):
        """Test handling of syntax errors"""
        code = "def broken( )"  # Invalid syntax
        analysis = analyze_function(code)
        assert "error" in analysis


class TestValidation:
    """Tests for the validation agent"""

    def test_validate_good_test(self):
        """Test validation of a good pytest"""
        code = """
import pytest

def test_simple():
    assert 1 + 1 == 2
"""
        result = validate_test(code)
        assert result["is_valid"] is True
        assert result["test_count"] == 1

    def test_validate_no_assertions(self):
        """Test validation fails with no assertions"""
        code = """
def test_empty():
    pass
"""
        result = validate_test(code)
        assert result["is_valid"] is False

    def test_validate_syntax_error(self):
        """Test validation catches syntax errors"""
        code = "def test_broken( )"  # Invalid
        result = validate_test(code)
        assert result["is_valid"] is False

    def test_validate_multiple_tests(self):
        """Test validation with multiple test functions"""
        code = """
import pytest

def test_one():
    assert True

def test_two():
    assert True

def test_three():
    with pytest.raises(ValueError):
        raise ValueError()
"""
        result = validate_test(code)
        assert result["is_valid"] is True
        assert result["test_count"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
