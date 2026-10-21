"""Pure text parsers for invoice-like documents."""
import re
from datetime import date
from typing import Dict, Optional

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_amount(raw: str) -> float:
    """Parse '$1,234.50', '₹ 1,234.50', '(45.00)' or '1.234,50' into a float.

    Parentheses mean negative. Raises ValueError if no number is present.
    """
    if raw is None or not str(raw).strip():
        raise ValueError("Empty amount")
    s = str(raw).strip()
    negative = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        raise ValueError(f"No number in amount: {raw!r}")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) <= 2 else s.replace(",", "")
    value = float(s)
    return -value if negative else value


def parse_date(raw: str) -> date:
    """Parse ISO (2024-03-05), D/M/Y (05/03/2024) or '5 Mar 2024'. Day-first for slashes."""
    s = raw.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)
    if m:
        return date(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
    raise ValueError(f"Unrecognised date: {raw!r}")


def extract_invoice_fields(text: str) -> Dict[str, Optional[object]]:
    """Pull invoice_number, invoice_date and total from raw invoice text; missing fields are None."""
    number = re.search(r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Za-z0-9-]+)", text, re.I)
    when = re.search(r"(?:invoice\s*)?date\s*[:]?\s*([0-9A-Za-z ,./-]+)", text, re.I)
    total = re.search(r"(?:grand\s+)?total(?:\s+due)?\s*[:]?\s*([^\n]+)", text, re.I)

    parsed_date = None
    if when:
        try:
            parsed_date = parse_date(when[1].strip().splitlines()[0])
        except ValueError:
            pass
    parsed_total = None
    if total:
        try:
            parsed_total = parse_amount(total[1])
        except ValueError:
            pass
    return {
        "invoice_number": number[1] if number else None,
        "invoice_date": parsed_date,
        "total": parsed_total,
    }
