## 2024-05-24 - Initialization
**Learning:** Initialized Bolt journal.
**Action:** Ready to track performance learnings.

## 2024-05-24 - Fast-path substring checks before regex matching
**Learning:** When optimizing Python regex hot paths (especially for unvalidated strings like log tokens), prioritizing broad fast-path substring checks (e.g., checking if 'cl' is in the string before executing the full regex) significantly improves performance over repeatedly calling `regex.search()` on strings that will never match.
**Action:** When using regex to parse massive strings (like build logs), implement early returns based on simple substring checks that accurately mirror the underlying regex's requirements.
