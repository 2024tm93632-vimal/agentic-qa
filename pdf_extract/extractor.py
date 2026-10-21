"""PDF I/O: text, tables and metadata extraction."""
from pathlib import Path
from typing import Dict, List, Optional

import pdfplumber


class PDFExtractionError(Exception):
    pass


def _open(path: str):
    p = Path(path)
    if not p.is_file():
        raise PDFExtractionError(f"File not found: {path}")
    if p.suffix.lower() != ".pdf":
        raise PDFExtractionError(f"Not a PDF file: {path}")
    try:
        return pdfplumber.open(p)
    except Exception as e:
        raise PDFExtractionError(f"Could not open PDF: {e}") from e


def extract_text(path: str, pages: Optional[List[int]] = None) -> str:
    """Return text of the given 1-based pages (all pages if None), joined by newlines."""
    with _open(path) as pdf:
        total = len(pdf.pages)
        selected = pages if pages is not None else list(range(1, total + 1))
        for n in selected:
            if n < 1 or n > total:
                raise PDFExtractionError(f"Page {n} out of range (1-{total})")
        return "\n".join((pdf.pages[n - 1].extract_text() or "") for n in selected)


def extract_tables(path: str) -> List[List[List[str]]]:
    """Return every table in the PDF as a list of rows; empty cells become ''."""
    tables = []
    with _open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                tables.append([[cell or "" for cell in row] for row in table])
    return tables


def get_metadata(path: str) -> Dict[str, object]:
    with _open(path) as pdf:
        meta = dict(pdf.metadata or {})
        meta["page_count"] = len(pdf.pages)
        return meta
