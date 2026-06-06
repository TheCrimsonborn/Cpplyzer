## 2025-03-08 - Fast Path for split_windows_args
**Learning:** The manual character-by-character parsing loop in `split_windows_args` is a hot path when processing compilation commands and response files. For arguments that do not contain quotes (e.g., standard compiler flags), this slow loop can be completely bypassed in favor of Python's highly optimized, native `.split()` method.
**Action:** Use a fast-path fallback (`if '"' not in command: return command.split()`) before entering the character-by-character loop in `split_windows_args` in `cpplyzer.py`.
