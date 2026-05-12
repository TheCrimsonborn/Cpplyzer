import timeit
from pathlib import Path
from cpplyzer import resolve_source_path

tokens = [
    "file1.cpp",
    "some/path/file2.cc",
    "\"another_file.cxx\"",
    "C:\\path\\to\\file.cpp",
    "very_long_path_name_with_lots_of_directories/and_more_directories/to/the/actual_file.c",
]
command_dir = Path("/mock/command/dir")
source_root = Path("/mock/source/root")

def run_bench():
    for t in tokens:
        resolve_source_path(t, command_dir, source_root)

if __name__ == "__main__":
    t = timeit.timeit(run_bench, number=100000)
    print(f"Baseline Time: {t:.4f} seconds")
