
## 2025-05-18 - Fast string checks for log parsers
**Learning:** For performance-critical functions that parse huge string outputs line-by-line (like clang-tidy or cl outputs), doing a manual string check (e.g. `if "error: " not in line and "warning: " not in line:`) BEFORE running `re.match` dramatically improves performance (e.g. 17s -> 11s), even if the regex seems simple.
**Action:** Always consider fast-path string sub-checks (like `in`) prior to regex execution for processing large unvalidated text.

## 2025-05-18 - `os.path.realpath` vs `Path(...).resolve()`
**Learning:** Instantiating `pathlib.Path` objects and calling `.resolve()` in a tight loop is surprisingly slow compared to using standard library functions like `os.path.realpath`. Replacing it in parsing paths sped up execution significantly (e.g., 12.3s -> 3.5s).
**Action:** When working on performance-critical paths, prefer string manipulation and `os.path` functions over `pathlib.Path`.
