
## 2024-05-18 - Fast-path parsing and regex pre-checks
**Learning:** For custom argument parsing loops (like `split_windows_args`), a fast-path fallback to Python's highly optimized native `.split()` when complex tokens like double-quotes (`"`) are not present drastically reduces character-by-character parsing overhead. Additionally, applying broad fast-path substring checks (e.g., `'cl' not in line.lower()`) before compiling/executing regular expressions avoids executing regex overhead on irrelevant lines.
**Action:** When optimizing performance-critical paths involving regex or custom token parsers, always look for a simple fast-path that can skip the expensive operation entirely based on the presence/absence of key characters.
