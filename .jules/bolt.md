## 2024-05-13 - Path resolution bottleneck in log parsing
**Learning:** Calling `Path.resolve()` on thousands of lines during compile log parsing is a major bottleneck because it creates many objects and does repeated syscalls for paths. Combining this with slow character-by-character string splitting when quotes aren't present makes log parsing much slower than necessary.
**Action:** Use `os.path.realpath(os.path.join(...))` instead of `Path.resolve()` in hot paths like `resolve_source_path`, and add a fast-path `.split()` to `split_windows_args` when no quotes are in the string.
