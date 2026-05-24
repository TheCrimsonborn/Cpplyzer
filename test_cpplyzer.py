import cpplyzer

def test_object_key_from_token():
    assert cpplyzer.object_key_from_token("file1.obj") == "file1.obj"
    assert cpplyzer.object_key_from_token("some/path/file2.obj") == None
    assert cpplyzer.object_key_from_token("\"another_file.obj\"") == "another_file.obj"
    assert cpplyzer.object_key_from_token("C:\\path\\to\\file.obj") == None
    assert cpplyzer.object_key_from_token("foo.OBJ") == "foo.obj"
    assert cpplyzer.object_key_from_token("not_an_obj_file.txt") == None
    assert cpplyzer.object_key_from_token("just_a_string") == None
    assert cpplyzer.object_key_from_token("@response_file.rsp") == None
    assert cpplyzer.object_key_from_token("something_else.obj.d") == "something_else.obj"
    assert cpplyzer.object_key_from_token("@C:\\temp\\file.obj.1234.jom") == None

def test_extract_cl_command():
    assert cpplyzer.extract_cl_command("cl.exe /c main.cpp") == "cl.exe /c main.cpp"
    assert cpplyzer.extract_cl_command("\"C:\\Program Files\\MSVC\\bin\\cl.exe\" /c foo.cpp") == "\"C:\\Program Files\\MSVC\\bin\\cl.exe\" /c foo.cpp"
    assert cpplyzer.extract_cl_command("g++ -c bar.cpp") == None
    assert cpplyzer.extract_cl_command(" cl -c test.cpp") == "cl -c test.cpp"
    assert cpplyzer.extract_cl_command("CL.EXE /c something.c") == "CL.EXE /c something.c"
    assert cpplyzer.extract_cl_command("& cl.exe /c hello.cpp") == "cl.exe /c hello.cpp"
    assert cpplyzer.extract_cl_command("just some random text without the magic word") == None
    assert cpplyzer.extract_cl_command("another line of text that has no compilation command in it whatsoever") == None
