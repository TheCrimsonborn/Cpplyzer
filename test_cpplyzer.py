import pytest
import cpplyzer

def test_split_windows_args_simple():
    assert cpplyzer.split_windows_args("a b c") == ["a", "b", "c"]
    assert cpplyzer.split_windows_args("cl.exe /c /O2 /MD main.cpp") == ["cl.exe", "/c", "/O2", "/MD", "main.cpp"]
    assert cpplyzer.split_windows_args("jom.exe -f Makefile.Release") == ["jom.exe", "-f", "Makefile.Release"]

def test_split_windows_args_quotes():
    assert cpplyzer.split_windows_args('"quoted arg with spaces" another_arg') == ["quoted arg with spaces", "another_arg"]
    assert cpplyzer.split_windows_args('something "with quotes" around') == ["something", "with quotes", "around"]
    assert cpplyzer.split_windows_args('mixed "quotes and spaces" test "with" multiple') == ["mixed", "quotes and spaces", "test", "with", "multiple"]

def test_split_windows_args_edge_cases():
    assert cpplyzer.split_windows_args("") == []
    assert cpplyzer.split_windows_args("   ") == []
    assert cpplyzer.split_windows_args("no_spaces_at_all") == ["no_spaces_at_all"]
    assert cpplyzer.split_windows_args("  spaces  at   ends  ") == ["spaces", "at", "ends"]

def test_split_windows_args_unclosed_quotes():
    assert cpplyzer.split_windows_args('"unclosed quote') == ["unclosed quote"]
