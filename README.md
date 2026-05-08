# Cpplyzer

Cpplyzer is an offline static-analysis orchestrator for Qt/qmake/MSVC C++
projects. It is designed for GitLab CI/CD jobs running in air-gapped Windows
environments.

Cpplyzer does not try to replace analyzers. It captures the real MSVC compile
commands from Qt `.pro` builds and runs locally installed analyzers such as
`clang-tidy` and `cppcheck`. Reports are written as HTML and JSON.

## Quick start

Create an editable config:

```bat
python cpplyzer.py init-config --force -o cpplyzer.json
```

Edit `cpplyzer.json` and set paths for:

- `toolchain.qmake`
- `toolchain.jom`
- `toolchain.vcvars`
- `analysis.clangTidy.path`
- `analysis.cppcheck.path`

Run for one `.pro` file:

```bat
python cpplyzer.py analyze C:\src\MyQtApp\MyQtApp.pro --config cpplyzer.json --output reports\cpplyzer
```

Run for every `.pro` file discovered under a workspace:

```bat
python cpplyzer.py analyze-many C:\src\workspace --config cpplyzer.json --output reports\cpplyzer
```

Open the multi-project dashboard:

```text
reports\cpplyzer\index.html
```

## Existing compile database

If the project already has `compile_commands.json`, skip qmake/jom capture:

```bat
python cpplyzer.py analyze C:\src\MyQtApp\MyQtApp.pro --config cpplyzer.json --compile-commands C:\src\MyQtApp\compile_commands.json
```

## Existing build log

If GitLab CI/CD already produces a build log with visible `cl.exe /c ... file.cpp`
commands, Cpplyzer can create `compile_commands.json` from that log:

```bat
python cpplyzer.py analyze C:\src\MyQtApp\MyQtApp.pro --config cpplyzer.json --build-log C:\gitlab-runner\build.log
```

## GitLab CI/CD behavior

Cpplyzer exits with `0` when analysis completes, even if findings exist. This
matches the current requirement: findings should be reported, not fail the build.
It exits non-zero only for tool/configuration/runtime errors.

Use `--strict-tools` in GitLab CI/CD if missing analyzers should fail the job.

The included `.gitlab-ci.yml` expects a Windows runner with a `windows` tag. It
runs:

```text
python C:\Tools\Cpplyzer\cpplyzer.py analyze-many $env:CI_PROJECT_DIR
```

and archives the HTML/JSON reports from:

```text
reports/cpplyzer/
```

The main artifact is:

```text
reports/cpplyzer/index.html
```

For GitLab groups such as `gitlab.company.local/group/subgroup`, there are two
valid operating modes:

- Put `.gitlab-ci.yml` in each repo and analyze that repo's workspace.
- Use a central analysis repo that clones multiple repos under one directory,
  then run `analyze-many` against that directory.

The second mode is useful when you want one dashboard across several independent
repos.

## Air-gapped packaging

Recommended layout on the GitLab runner node:

```text
C:\Tools\Cpplyzer\
  cpplyzer.py
  cpplyzer.json
  tools\
    llvm\bin\clang-tidy.exe
    cppcheck\cppcheck.exe
```

The script uses only Python standard library modules. If Python is not allowed
on the GitLab runner node, package it with PyInstaller on a matching Windows machine
and move the generated executable by USB.

## Notes for Qt/MSVC

Cpplyzer runs:

```text
qmake <project.pro> <build.qmakeArgs>
jom <build.jomDryRunArgs>
```

The default dry-run argument is `-n`. If your `jom` version expects a different
dry-run flag, change `build.jomDryRunArgs` in `cpplyzer.json`.

The dry-run output is parsed for `cl.exe /c ... file.cpp` commands and written
as:

```text
build\cpplyzer-capture\<project>\compile_commands.json
```

Some Qt/qmake projects generate a top-level Makefile that only delegates to
`Makefile.Release` or `Makefile.Debug`. In that case Cpplyzer automatically
tries a second dry-run with:

```text
jom -n -f Makefile.Release
jom -n -f Makefile.Debug
```

You can control this with `build.fallbackMakefiles` in `cpplyzer.json`.

When jom prints compile commands that end with a temporary MSVC response file,
for example `@C:\WINDOWS\TEMP\main.obj.1234.jom`, Cpplyzer first tries to read
that response file. If jom has already removed it, Cpplyzer falls back to the
generated `Makefile.Release` or `Makefile.Debug` and maps the object file back
to its source file.

## Discovery

`analyze-many` recursively searches for `.pro` files. It ignores common
generated/build folders such as `.git`, `build`, `out`, `reports`, `release`,
`debug`, and `GeneratedFiles`. Adjust `discovery.ignoreDirs` or
`discovery.ignoreProNames` in `cpplyzer.json` if your repository has special
folders that should be skipped.

## Report contents

Each finding includes:

- analyzer name
- severity
- rule/check id
- file, line, and column
- message
- source snippet when the file is available locally
