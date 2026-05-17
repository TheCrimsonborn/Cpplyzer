## 2024-05-17 - [Fast path checking for regex performance]
**Learning:** Adding a direct string containment fast path check with `in` (checking permutations of case directly, instead of converting the string with `.lower()`) is noticeably faster than using the regex engine alone, even when evaluating heavily filtered subsets of strings. Doing an `in` check on 4 different case strings is ~25% faster than `.lower()` for hot paths because it avoids the overhead of allocating a new string.
**Action:** Use fast path substring checks for frequent hot loop regex matches.
