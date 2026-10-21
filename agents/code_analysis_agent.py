"""
Code Analysis Agent - Parses and analyzes Python code using AST
"""
import ast
import json
from typing import Dict, List, Any


def describe_function(node) -> Dict[str, Any]:
    """Structured summary of one (async) function node: args, return type, raises, docstring."""
    args = node.args
    positional = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    args_info = [
        {"name": a.arg, "type": ast.unparse(a.annotation) if a.annotation else None}
        for a in positional
    ]
    if args.vararg:
        args_info.append({"name": "*" + args.vararg.arg, "type": None})
    if args.kwarg:
        args_info.append({"name": "**" + args.kwarg.arg, "type": None})

    raised = {ast.unparse(c.exc.func if isinstance(c.exc, ast.Call) else c.exc)
              for c in ast.walk(node) if isinstance(c, ast.Raise) and c.exc}
    return {
        "name": node.name,
        "args": args_info,
        "returns": ast.unparse(node.returns) if node.returns else None,
        "raises": sorted(raised),
        "docstring": ast.get_docstring(node) or "",
        "line": node.lineno,
    }


def analyze_function(source_code: str) -> Dict[str, Any]:
    """
    Extract structured information from Python code using AST.

    Args:
        source_code: Python source code to analyze

    Returns:
        Dictionary containing extracted function details and imports
    """

    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return {
            "error": f"Syntax error: {e}",
            "functions": [],
            "imports": []
        }

    result = {
        "functions": [],
        "imports": [],
        "classes": []
    }

    # Extract imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "type": "import",
                    "module": alias.name,
                    "alias": alias.asname
                })
        elif isinstance(node, ast.ImportFrom):
            result["imports"].append({
                "type": "from",
                "module": node.module,
                "names": [alias.name for alias in node.names]
            })

    # Extract function details
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].append(describe_function(node))

        if isinstance(node, ast.ClassDef):
            class_info = {
                "name": node.name,
                "methods": [],
                "docstring": ast.get_docstring(node) or "",
                "line": node.lineno
            }

            # Extract methods
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    class_info["methods"].append(item.name)

            result["classes"].append(class_info)

    return result


def build_enriched_prompt(source_code: str, few_shot_examples: List[str] = None) -> str:
    """
    Build a rich prompt using AST analysis for better test generation.

    Args:
        source_code: The Python code to test
        few_shot_examples: List of similar approved tests for few-shot learning

    Returns:
        Enhanced prompt for the LLM
    """

    analysis = analyze_function(source_code)

    # Build AST summary section
    ast_summary = ""

    if analysis.get("error"):
        ast_summary = f"Error analyzing code: {analysis['error']}\n"
    else:
        for func in analysis["functions"]:
            args_str = ", ".join([
                f"{arg['name']}: {arg['type']}" if arg['type'] else arg['name']
                for arg in func['args']
            ])

            raises_str = ", ".join(func['raises']) if func['raises'] else "nothing"

            ast_summary += f"""
Function: {func['name']}({args_str})
  Returns: {func['returns'] or 'None'}
  Raises: {raises_str}
  Docstring: {func['docstring'][:100] if func['docstring'] else 'none'}
"""

    # Build few-shot section
    examples_section = ""
    if few_shot_examples:
        examples_section = "\n## SIMILAR APPROVED TESTS FROM THIS PROJECT:\n"
        for i, ex in enumerate(few_shot_examples, 1):
            examples_section += f"\nExample {i}:\n{ex}\n---\n"

    prompt = f"""You are an expert QA engineer for this specific Python project.

## FUNCTION TO TEST:
```python
{source_code}
```

## CODE ANALYSIS:
{ast_summary}

{examples_section}

## INSTRUCTIONS:
Generate pytest tests covering:
1. Happy path with typical inputs
2. Edge cases based on the argument types analyzed above
3. All exception scenarios listed in Raises above
4. Boundary values if applicable to the types

Requirements:
- Use pytest.raises() for exception tests
- Output ONLY valid pytest code
- No explanations or markdown
- Each test function must start with 'test_'
"""
    return prompt


if __name__ == "__main__":
    # Test the analyzer
    sample = """
def calculate_discount(price: float, discount_pct: float) -> float:
    \"\"\"Calculate final price after applying discount percentage.\"\"\"
    if price < 0:
        raise ValueError("Price cannot be negative")
    if discount_pct < 0 or discount_pct > 100:
        raise ValueError("Discount must be between 0 and 100")
    return price * (1 - discount_pct / 100)
"""

    print("=" * 60)
    print("CODE ANALYSIS")
    print("=" * 60)
    analysis = analyze_function(sample)
    print(json.dumps(analysis, indent=2))

    print("\n" + "=" * 60)
    print("ENRICHED PROMPT FOR LLM")
    print("=" * 60)
    prompt = build_enriched_prompt(sample)
    print(prompt)
