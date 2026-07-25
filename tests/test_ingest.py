from complai.ingest import normalise


def test_dehyphenates_across_line_breaks():
    assert normalise("commu-\nnication") == "communication"


def test_collapses_whitespace_but_keeps_paragraphs():
    assert normalise("a   b\n\n\n\nc") == "a b\n\nc"


def test_strips_bare_page_numbers():
    assert normalise("end of section\n\n27\n\nSECTION G") == "end of section\n\nSECTION G"


def test_preserves_mandated_warning_text_verbatim():
    raw = "The vast majority of retail investor  accounts lose money\nwhen trading CFDs."
    assert normalise(raw) == "The vast majority of retail investor accounts lose money when trading CFDs."


def test_numbered_paragraphs_start_their_own_block():
    raw = "warning. 3.5.12. In particular, the CFD provider shall not send"
    assert normalise(raw) == "warning.\n\n3.5.12. In particular, the CFD provider shall not send"


def test_paragraph_numbering_is_never_split_mid_marker():
    """Regression: a zero-width match fired inside "3.5.12." and split it into
    "3." + "5.12.", destroying every cross-reference in the document."""
    assert "3.5.12." in normalise("warning. 3.5.12. In particular, the provider shall")
    assert "3.4.10." in normalise("text. 3.4.10. In relation to Tiered Fees-Spreads, we")


def test_section_headings_start_their_own_block():
    raw = "in the format specified in Section D. SECTION B Durable medium"
    assert normalise(raw) == "in the format specified in Section D.\n\nSECTION B Durable medium"
