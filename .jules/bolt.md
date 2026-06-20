
## 2024-05-15 - Fast Path for String Splitting without Quotes
**Learning:** In custom string parsing loops, checking for the absence of complex tokens (like `"` with `if '"' not in string:`) allows for a fast-path fallback to Python's highly optimized `.split()`. Additionally, iterating via `for char in command` instead of a `while` loop with manual index tracking is faster and more readable.
**Action:** Before falling back to character-by-character parsing, check for a fast path using native methods. Prefer `for` loops over `while` loops for simple character iterations.
