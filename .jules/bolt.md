## 2024-05-18 - Fast paths for unquoted argument parsing
**Learning:** When parsing Windows command arguments, strings without double quotes can be parsed directly and accurately with Python's native `.split()`.
**Action:** Use this as a fast-path optimization before entering a character-by-character parsing loop to drastically reduce string processing overhead.
