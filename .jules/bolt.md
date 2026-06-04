## 2025-05-19 - Fast-path fallback for parsing arguments
**Learning:** In custom argument parsing loops like `split_windows_args`, avoiding character-by-character string parsing by checking for a complex token (like `"`) enables a much faster native string operation (`.split()`).
**Action:** Use native Python string operations where possible by introducing quick checks for complex features, falling back on Python's native implementations in common "happy paths".
