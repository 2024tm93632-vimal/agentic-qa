from datetime import date

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pdf_extract import (PDFExtractionError, extract_invoice_fields, extract_tables,
                         extract_text, get_metadata, parse_amount, parse_date)


@pytest.fixture
def invoice_pdf(tmp_path):
    path = tmp_path / "invoice.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Invoice")
    for i, line in enumerate(["Invoice No: INV-2024-007", "Date: 05/03/2024", "Total Due: $1,234.50"]):
        c.drawString(72, 780 - i * 20, line)
    c.showPage()
    c.drawString(72, 780, "Page two")
    c.save()
    return str(path)


@pytest.mark.parametrize("raw,expected", [
    ("$1,234.50", 1234.50), ("₹ 99", 99.0), ("(45.00)", -45.0), ("-3.5", -3.5),
    ("1.234,50", 1234.50), ("12,5", 12.5), ("1,234", 1234.0),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "   ", "abc", None])
def test_parse_amount_rejects_non_numbers(raw):
    with pytest.raises(ValueError):
        parse_amount(raw)


@pytest.mark.parametrize("raw,expected", [
    ("2024-03-05", date(2024, 3, 5)), ("05/03/2024", date(2024, 3, 5)),
    ("5 Mar 2024", date(2024, 3, 5)), ("5 March, 2024", date(2024, 3, 5)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["yesterday", "31/02/2024", "2024/03/05"])
def test_parse_date_rejects_invalid(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def test_extract_invoice_fields_from_text():
    fields = extract_invoice_fields("Invoice No: INV-9\nDate: 2024-01-31\nTotal: $10.00")
    assert fields == {"invoice_number": "INV-9", "invoice_date": date(2024, 1, 31), "total": 10.0}


def test_extract_invoice_fields_missing_values_are_none():
    assert extract_invoice_fields("nothing useful here") == {
        "invoice_number": None, "invoice_date": None, "total": None}


def test_extract_text_and_fields_from_real_pdf(invoice_pdf):
    text = extract_text(invoice_pdf)
    fields = extract_invoice_fields(text)
    assert fields["invoice_number"] == "INV-2024-007"
    assert fields["total"] == 1234.50
    assert "Page two" in text


def test_extract_text_single_page(invoice_pdf):
    assert "Page two" not in extract_text(invoice_pdf, pages=[1])


def test_extract_text_page_out_of_range(invoice_pdf):
    with pytest.raises(PDFExtractionError):
        extract_text(invoice_pdf, pages=[3])


def test_metadata_has_page_count(invoice_pdf):
    assert get_metadata(invoice_pdf)["page_count"] == 2


def test_extract_tables_returns_list(invoice_pdf):
    assert extract_tables(invoice_pdf) == []


def test_missing_and_non_pdf_files(tmp_path):
    with pytest.raises(PDFExtractionError):
        extract_text(str(tmp_path / "nope.pdf"))
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(PDFExtractionError):
        extract_text(str(txt))
