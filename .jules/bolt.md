## 2024-05-24 - Optimizing Hot-Path Log Parsing
**Learning:** Checking for substrings via `.lower()` acts as a fast-path for heavily invoked regex searches. A fast-path case-insensitive substring check (`if "cl" not in line.lower(): return None`) avoids full regex evaluation on irrelevant tokens, significantly speeding up hot paths without relying on micro-optimizations that damage code readability.
**Action:** Use simple, readable fast-path string checks before compiling/executing regular expressions on hot paths to immediately skip irrelevant string data.
