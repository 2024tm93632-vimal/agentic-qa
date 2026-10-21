"""
Sample utility functions for testing the agentic-qa system.
"""


def calculate_discount(price: float, discount_pct: float) -> float:
    """
    Calculate final price after applying discount percentage.

    Args:
        price: Original price (must be non-negative)
        discount_pct: Discount percentage (0-100)

    Returns:
        Final price after discount

    Raises:
        ValueError: If price is negative or discount is outside 0-100
    """
    if price < 0:
        raise ValueError("Price cannot be negative")
    if discount_pct < 0 or discount_pct > 100:
        raise ValueError("Discount must be between 0 and 100")
    return price * (1 - discount_pct / 100)


def divide(a: float, b: float) -> float:
    """
    Divide a by b.

    Args:
        a: Numerator
        b: Denominator

    Returns:
        Result of a / b

    Raises:
        ValueError: If b is zero
    """
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b


def find_max(numbers: list) -> int:
    """
    Find the maximum number in a list.

    Args:
        numbers: List of numbers

    Returns:
        Maximum value

    Raises:
        ValueError: If list is empty
    """
    if not numbers:
        raise ValueError("List cannot be empty")
    return max(numbers)


def is_palindrome(text: str) -> bool:
    """
    Check if a string is a palindrome.

    Args:
        text: String to check

    Returns:
        True if palindrome, False otherwise
    """
    cleaned = text.lower().replace(" ", "")
    return cleaned == cleaned[::-1]
