import pytest
from cpplyzer import normalize_make_output

def test_normalize_make_output_empty():
    assert normalize_make_output("") == []
    assert normalize_make_output("   \n\n  \n") == []

def test_normalize_make_output_no_continuation():
    text = "line 1\nline 2\nline 3"
    assert normalize_make_output(text) == ["line 1", "line 2", "line 3"]

def test_normalize_make_output_with_continuation():
    text = "part 1^\npart 2"
    assert normalize_make_output(text) == ["part 1 part 2"]

def test_normalize_make_output_multiple_continuations():
    text = "part 1^\npart 2^\npart 3"
    assert normalize_make_output(text) == ["part 1 part 2 part 3"]

def test_normalize_make_output_skip_empty_lines():
    text = "part 1^\n\n\npart 2"
    assert normalize_make_output(text) == ["part 1 part 2"]

def test_normalize_make_output_trailing_continuation():
    text = "part 1^\npart 2^\n"
    assert normalize_make_output(text) == ["part 1 part 2"]

def test_normalize_make_output_stripping():
    text = "  line 1  \n  line 2  "
    assert normalize_make_output(text) == ["line 1", "line 2"]

def test_normalize_make_output_continuation_stripping():
    text = "  part 1  ^\n  part 2  "
    assert normalize_make_output(text) == ["part 1     part 2"]

def test_normalize_make_output_complex():
    text = "line 1\n\nline 2 part 1^\nline 2 part 2^\n\nline 2 part 3\n\nline 3^\n"
    assert normalize_make_output(text) == [
        "line 1",
        "line 2 part 1 line 2 part 2 line 2 part 3",
        "line 3"
    ]

# Testing with exactly the same string as the reviewer complained about
def test_normalize_make_output_complex_triple_quotes():
    text = """
    line 1

    line 2 part 1^
    line 2 part 2^

    line 2 part 3

    line 3^
    """
    assert normalize_make_output(text) == [
        "line 1",
        "line 2 part 1     line 2 part 2     line 2 part 3",
        "line 3"
    ]
