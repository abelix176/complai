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
