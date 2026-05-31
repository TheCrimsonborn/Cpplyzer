## 2024-05-24 - split_windows_args fast path
**Learning:** For custom argument parsing loops (like `split_windows_args`), character-by-character parsing introduces significant overhead in Python. Many strings do not contain complex tokens (like double quotes `"`).
**Action:** Use a fast-path fallback to Python's highly optimized native `.split()` when complex tokens like double-quotes (`"`) are not present to drastically reduce character-by-character parsing overhead.
