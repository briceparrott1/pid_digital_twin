import os

from parsers.sop_parser import parse_sop

SOP_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "sop")


def test_parse_sop_includes_tables_nested_in_content_controls():
    text = parse_sop(os.path.join(SOP_DIR, "sop1.docx"))

    # Operating limits table (top-level table)
    assert "F-715 A and B Particulate Filters" in text
    assert "275" in text

    # Incompatible parts table is wrapped in a content control (w:sdt) and
    # was previously skipped by doc.tables.
    assert "Part A" in text
    assert "Part B" in text
    assert "F-715A" in text
    assert "DPI-715A" in text
    assert "FROM_NGL_HEAT_RECOVERY_EXCHANGER_WARM_FEED" in text
    assert "MV-745-08" in text
