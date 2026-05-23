## 2024-05-18 - Fast-path substring checks vs String parsing

**Learning:** When optimizing Python regex hot paths (especially for unvalidated strings like log tokens), prioritize broad fast-path substring checks. For case-insensitive checks on long strings, explicitly checking exact string permutations (e.g., `if '.obj' not in token and '.OBJ' not in token...`) is significantly faster than using `.lower()` before the `in` check. Manual string parsing (like `rfind`) can actually be slower than executing the regex on the heavily filtered subset. Furthermore, we must not rewrite the name extraction logic with `rfind` if it could break on cross-platform cases like `Path` objects in Python which behave differently.

**Action:** Use fast path substring checks for hot paths without altering the underlying extraction logic. Check permutations instead of `.lower()` for maximum speed.
