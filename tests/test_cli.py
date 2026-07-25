import pytest
from complai.cli import _read_text


def test_reads_text_from_positional_argument():
    class Args:
        text = "inline copy"
        file = None
    assert _read_text(Args()) == "inline copy"


def test_reads_text_from_file(tmp_path):
    path = tmp_path / "copy.txt"
    path.write_text("copy from disk", encoding="utf-8")
    class Args:
        text = None
        file = str(path)
    assert _read_text(Args()) == "copy from disk"


def test_missing_input_is_an_error():
    class Args:
        text = None
        file = None
    with pytest.raises(SystemExit):
        _read_text(Args())
