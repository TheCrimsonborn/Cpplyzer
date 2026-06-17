## 2025-05-24 - Performance Optimizations
**Learning:** Found that string parsing in Python using `while` loops is significantly slower than `for` loops or native string methods.
**Action:** Use native string methods like `.split(" ")` when possible and `for` loops instead of `while` loops for character iteration.
