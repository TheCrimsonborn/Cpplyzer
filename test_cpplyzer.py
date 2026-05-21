from cpplyzer import extract_cl_command
import cpplyzer

def test_extract_cl_command():
    # The regex only matches if "cl" is at the start of string or preceded by whitespace/& OR if it's in quotes like "\cl.exe"
    # C:\MSVC\bin\cl.exe -c test.c does not match because it's not in quotes and cl.exe is preceded by backslash, not whitespace
    assert extract_cl_command("cl.exe /c main.cpp") == "cl.exe /c main.cpp"
    assert extract_cl_command('"C:\\MSVC\\bin\\cl.exe" -c test.c') == '"C:\\MSVC\\bin\\cl.exe" -c test.c'
    assert extract_cl_command("  & cl.exe /nologo /c test.cpp") == "cl.exe /nologo /c test.cpp"
    assert extract_cl_command("some very long line  cl.exe /c") == "cl.exe /c"

    # Should be ignored (no /c or -c)
    assert extract_cl_command("cl.exe main.cpp") is None
    assert extract_cl_command("cl.exe main.cpp /link something") is None

    # Fast path rejections
    assert extract_cl_command("g++ -c main.cpp") is None
    assert extract_cl_command("just some random log output that doesn't contain the command") is None
    assert extract_cl_command("link.exe main.obj") is None
