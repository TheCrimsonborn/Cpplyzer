
## 2024-05-18 - Fast-path parsing for strings
**Learning:** Manual character-by-character parsing loops in Python are very slow compared to native C-based functions like `.split()`.
**Action:** When creating custom argument or string parsing loops that handle specific characters (like quotes `"`), implement a fast-path fallback using standard library methods (e.g., `if '"' not in s: return s.split()`) to drastically reduce overhead when those specific characters are not present.
