## 2024-05-23 - Fast string checks before Regex
**Learning:** Checking for substrings using `in` and `lower()` is significantly faster than using regexes for parsing large build logs when most lines don't match. Specifically, adding a fast-path check for `"cl"` and `"/c"` or `" -c "` in `extract_cl_command` yields a ~2x performance improvement by avoiding regex engine overhead on irrelevant log lines.
**Action:** Always prefer pre-filtering with `str.lower()` and `in` before executing expensive compiled regular expressions in loop-heavy parsing functions.
