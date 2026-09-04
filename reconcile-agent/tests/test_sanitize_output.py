"""Test markdown sanitization in QA responses"""

import pytest
from app.agents.qa_agent import sanitize_markdown


def test_sanitize_bold():
    """Test removal of bold markdown"""
    input_text = "This is **bold** text"
    expected = "This is bold text"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_bold_italic():
    """Test removal of bold italic markdown"""
    input_text = "This is ***bold italic*** text"
    expected = "This is bold italic text"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_italic():
    """Test removal of italic markdown"""
    input_text = "This is *italic* text"
    expected = "This is italic text"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_code():
    """Test removal of inline code markdown"""
    input_text = "This is `code` text"
    expected = "This is code text"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_headers():
    """Test removal of header markdown"""
    input_text = "# Header 1\n## Header 2\n### Header 3"
    expected = "Header 1\nHeader 2\nHeader 3"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_links():
    """Test removal of link markdown"""
    input_text = "Check [this link](https://example.com) out"
    expected = "Check this link out"
    assert sanitize_markdown(input_text) == expected


def test_sanitize_complex_text():
    """Test sanitization of complex markdown text"""
    input_text = """
    **Partial Settlements**: Three payments (pay_test_0041, pay_test_0042, pay_test_0043) 
    have been identified with the reason for exception being ***PARTIAL_SETTLEMENT***. 
    This means that these payments were only *partially* settled.
    """
    result = sanitize_markdown(input_text)
    
    # Check that all markdown is removed
    assert "**" not in result
    assert "***" not in result
    assert "*" not in result
    
    # Check that content is preserved
    assert "Partial Settlements" in result
    assert "pay_test_0041" in result
    assert "PARTIAL_SETTLEMENT" in result


def test_sanitize_real_qa_output():
    """Test sanitization on actual QA output format"""
    input_text = """The batch has a total of 52 processed records, with 42 matched and 10 exceptions. The exceptions indicate issues that prevented matches from occurring. The reasons for these exceptions are as follows:

1. **Partial Settlements**: Three payments (pay_test_0041, pay_test_0042, pay_test_0043) have been identified with the reason for exception being "PARTIAL_SETTLEMENT." This means that these payments were only partially settled and do not match fully with corresponding entries.

2. **Duplicate UTRs**: Two payments (pay_test_0044, pay_test_0045) are flagged for having "DUPLICATE_UTR." This indicates that there are multiple entries for the same Unique Transaction Reference, leading to a conflict in matching.

3. **Missing Bank Entries**: Two payments (pay_test_0046, pay_test_0047) are marked as "MISSING_BANK_ENTRY." This suggests that the expected bank entries corresponding to these payments are not present, resulting in no match.

4. **Amount Mismatch**: One payment (pay_test_0048) has an "AMOUNT_MISMATCH," meaning the amounts recorded do not align with what was expected, preventing a successful match.

5. **Orphan Bank Entries**: There are two instances of "MISSING_SETTLEMENT," categorized as orphan bank entries, which implies that there are bank entries without corresponding payment records, thereby causing them to be unmatched.

These issues account for the exceptions in the reconciliation, which contribute to why no matches are present for those specific entries."""

    result = sanitize_markdown(input_text)
    
    # Verify all bold markdown is removed
    assert "**" not in result
    assert "***" not in result
    
    # Verify content is preserved
    assert "Partial Settlements" in result
    assert "Duplicate UTRs" in result
    assert "Missing Bank Entries" in result
    assert "Amount Mismatch" in result
    assert "Orphan Bank Entries" in result
    
    # Verify it's cleaner
    assert "Partial Settlements:" in result  # Should keep the colon
    assert "pay_test_0041" in result  # Should keep payment IDs


if __name__ == "__main__":
    # Run a quick test
    sample = "**Bold** text with *italic* and `code`"
    print(f"Input:  {sample}")
    print(f"Output: {sanitize_markdown(sample)}")
