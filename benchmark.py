import timeit
import cpplyzer

tokens = [
    "file1.obj",
    "some/path/file2.obj",
    "\"another_file.obj\"",
    "@response_file.rsp",
    "not_an_obj_file.txt",
    "C:\\path\\to\\file.obj",
    "very_long_path_name_with_lots_of_directories/and_more_directories/to/the/actual_file.obj",
    "something_else.obj.d",
    "just_a_string"
]

def run_bench():
    for t in tokens:
        cpplyzer.object_key_from_token(t)

if __name__ == "__main__":
    t = timeit.timeit(run_bench, number=100000)
    print(f"Baseline Time: {t:.4f} seconds")

# Added by Bolt
commands = [
    "gcc -c main.c -o main.o",
    "cl.exe /c /O2 /I include main.cpp",
    "jom -n -f Makefile.Release",
    "cl.exe /c \"C:\\path with spaces\\main.cpp\" -I\"D:\\include dir\"",
    "\"C:\\Program Files\\Compiler\\cl.exe\" /c main.cpp",
]

def run_bench_commands():
    for c in commands:
        cpplyzer.split_windows_args(c)

if __name__ == "__main__":
    t = timeit.timeit(run_bench_commands, number=100000)
    print(f"Command Parsing Time: {t:.4f} seconds")
