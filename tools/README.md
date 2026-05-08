# Offline analyzer binaries

Place air-gapped analyzer binaries here if you want paths to stay relative to
`cpplyzer.json`.

Suggested layout:

```text
tools/
  llvm/bin/clang-tidy.exe
  cppcheck/cppcheck.exe
```

You can also point `cpplyzer.json` at absolute paths on the Jenkins node.

