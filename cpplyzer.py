#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import functools
import datetime as dt
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from defusedxml import ElementTree as ET


VERSION = "0.1.0"

SOURCE_EXTENSIONS = {".c", ".cc", ".cpp", ".cxx", ".c++"}

DEFAULT_CONFIG: Dict[str, Any] = {
    "toolchain": {
        "qmake": "qmake",
        "jom": "jom",
        "vcvars": "",
        "windeployqt": "",
    },
    "build": {
        "qmakeArgs": [
            "-spec",
            "win32-msvc",
            "CONFIG+=release",
        ],
        "jomDryRunArgs": [
            "-n",
        ],
        "fallbackMakefiles": [
            "Makefile.Release",
            "Makefile.Debug",
        ],
        "environment": {},
        "skipQmake": False,
    },
    "discovery": {
        "ignoreDirs": [
            ".git",
            ".svn",
            ".hg",
            ".vs",
            ".vscode",
            "__pycache__",
            "build",
            "out",
            "reports",
            "release",
            "debug",
            "GeneratedFiles",
        ],
        "ignoreProNames": [],
    },
    "analysis": {
        "sourceExtensions": [".c", ".cc", ".cpp", ".cxx"],
        "compileCommands": "",
        "failOnMissingTool": False,
        "clangTidy": {
            "enabled": True,
            "path": "clang-tidy",
            "jobs": 1,
            "checks": (
                "clang-analyzer-*,bugprone-*,cert-*,cppcoreguidelines-*,"
                "modernize-*,performance-*,portability-*,qt-*,readability-*"
            ),
            "extraArgs": [],
            "headerFilter": ".*",
        },
        "cppcheck": {
            "enabled": True,
            "path": "cppcheck",
            "enable": "all",
            "inconclusive": True,
            "suppressions": [
                "missingIncludeSystem",
            ],
            "extraArgs": [
                "--inline-suppr",
            ],
        },
    },
    "report": {
        "includeSnippets": True,
        "contextLines": 2,
        "maxIssues": 10000,
        "pathFilters": {
            "includeRoots": [],
            "excludeRoots": [],
        },
        "ruleDocs": {
            "paths": [
                "rules/clang-tidy.json",
                "rules/cppcheck.json",
            ]
        },
    },
}


@dataclass
class CommandResult:
    tool: str
    command: List[str]
    cwd: str
    exit_code: int
    duration_seconds: float
    stdout_path: str
    stderr_path: str


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Optional[Path]) -> Tuple[Dict[str, Any], Optional[Path]]:
    if not config_path:
        return deepcopy(DEFAULT_CONFIG), None
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        user_config = json.load(handle)
    return deep_merge(DEFAULT_CONFIG, user_config), config_path.resolve().parent


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def read_text_lossy(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_executable(raw: str, config_dir: Optional[Path]) -> str:
    if not raw:
        return raw
    expanded = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return str(candidate)
    if config_dir:
        from_config = config_dir / candidate
        if from_config.exists():
            return str(from_config)
    return expanded


def resolve_optional_path(raw: str, base_dir: Path, config_dir: Optional[Path]) -> Optional[Path]:
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(expanded)
    if candidate.is_absolute():
        return candidate
    if config_dir and (config_dir / candidate).exists():
        return (config_dir / candidate).resolve()
    return (base_dir / candidate).resolve()


def executable_exists(path_or_name: str) -> bool:
    if not path_or_name:
        return False
    expanded = os.path.expandvars(os.path.expanduser(path_or_name))
    path = Path(expanded)
    if path.is_absolute() or "\\" in expanded or "/" in expanded:
        return path.exists()
    return shutil.which(expanded) is not None


def windows_cmdline(command: Sequence[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def log_excerpt(path: str, max_lines: int = 40, max_chars: int = 5000) -> str:
    log_path = Path(path)
    if not log_path.exists():
        return ""
    text = read_text_lossy(log_path).strip()
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... truncated; see {log_path}"]
    excerpt = "\n".join(lines)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars] + f"\n... truncated; see {log_path}"
    return excerpt


def command_failure_message(result: CommandResult, label: Optional[str] = None) -> str:
    name = label or result.tool
    message = [
        f"{name} failed with exit code {result.exit_code}.",
        f"cwd: {result.cwd}",
        f"command: {windows_cmdline(result.command)}",
    ]
    stderr = log_excerpt(result.stderr_path)
    stdout = log_excerpt(result.stdout_path)
    if stderr:
        message.append(f"stderr:\n{stderr}")
    if stdout:
        message.append(f"stdout:\n{stdout}")
    message.append(f"stdout log: {result.stdout_path}")
    message.append(f"stderr log: {result.stderr_path}")
    return "\n".join(message)


def run_command(
    tool: str,
    command: Sequence[str],
    cwd: Path,
    log_dir: Path,
    env_overrides: Optional[Dict[str, str]] = None,
    vcvars: str = "",
) -> CommandResult:
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / f"{tool}.stdout.log"
    stderr_path = log_dir / f"{tool}.stderr.log"
    command_path = log_dir / f"{tool}.command.txt"
    env = os.environ.copy()
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})

    display_command = [str(part) for part in command]
    command_line = windows_cmdline(display_command)
    command_details = [
        f"tool: {tool}",
        f"cwd: {cwd}",
        f"command: {command_line}",
    ]
    if vcvars:
        command_details.append(f"vcvars: {vcvars}")
    if env_overrides:
        command_details.append("environment overrides:")
        for key in sorted(env_overrides):
            command_details.append(f"  {key}={env_overrides[key]}")
    command_path.write_text("\n".join(command_details) + "\n", encoding="utf-8", newline="\n")
    start = time.monotonic()

    if vcvars and os.name == "nt":
        vcvars_path = Path(vcvars)
        if (vcvars_path.is_absolute() or "\\" in vcvars or "/" in vcvars) and not vcvars_path.exists():
            raise FileNotFoundError(f"vcvars batch file not found: {vcvars}")
        wrapped_command = f'cmd.exe /d /s /c "call "{vcvars}" && {command_line}"'
        command_path.write_text(
            "\n".join(command_details + [f"wrapped command: {wrapped_command}"]) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run(
            wrapped_command,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    else:
        completed = subprocess.run(
            display_command,
            cwd=str(cwd),
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    duration = time.monotonic() - start
    stdout_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
    return CommandResult(
        tool=tool,
        command=display_command,
        cwd=str(cwd),
        exit_code=completed.returncode,
        duration_seconds=round(duration, 3),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )


def normalize_make_output(text: str) -> List[str]:
    lines: List[str] = []
    buffer = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.endswith("^"):
            buffer += line[:-1] + " "
            continue
        if buffer:
            line = buffer + line
            buffer = ""
        lines.append(line.strip())
    if buffer.strip():
        lines.append(buffer.strip())
    return lines


def split_windows_args(command: str) -> List[str]:
    args: List[str] = []
    current: List[str] = []
    in_quotes = False
    i = 0
    while i < len(command):
        char = command[i]
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif char.isspace() and not in_quotes:
            if current:
                args.append("".join(current).strip('"'))
                current = []
        else:
            current.append(char)
        i += 1
    if current:
        args.append("".join(current).strip('"'))
    return args


@functools.lru_cache(maxsize=None)
def response_file_path(token: str) -> Optional[Path]:
    cleaned = token.strip().strip('"')
    if not cleaned.startswith("@") or len(cleaned) <= 1:
        return None
    return Path(cleaned[1:])


def read_response_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return read_text_lossy(path)


def archive_response_file(path: Path, archive_dir: Optional[Path]) -> None:
    if not archive_dir or not path.exists():
        return
    archive_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(path))
    target = archive_dir / safe_name
    try:
        shutil.copyfile(path, target)
    except OSError:
        pass


def expand_response_files(
    tokens: Sequence[str],
    command_dir: Path,
    archive_dir: Optional[Path],
    warnings: List[str],
) -> List[str]:
    expanded: List[str] = []
    for token in tokens:
        rsp_path = response_file_path(token)
        if not rsp_path:
            expanded.append(token)
            continue
        candidates = [rsp_path]
        if not rsp_path.is_absolute():
            candidates.insert(0, command_dir / rsp_path)
        resolved = next((candidate for candidate in candidates if candidate.exists()), None)
        if not resolved:
            warnings.append(f"Response file not found while parsing compile command: {rsp_path}")
            expanded.append(token)
            continue
        archive_response_file(resolved, archive_dir)
        response_text = read_response_file(resolved)
        if response_text is None:
            warnings.append(f"Response file could not be read: {resolved}")
            expanded.append(token)
            continue
        response_args = split_windows_args(response_text.replace("\r", " ").replace("\n", " "))
        expanded.extend(response_args)
    return expanded


def object_key_from_token(token: str) -> Optional[str]:
    r"""
    Extracts the object key from a compilation token.
    ⚡ Bolt Optimization: Replaced regex `(?i)(?P<object>[^\\/]+?\.obj)(?:\..*)?$` with
    native string operations and avoided unconditional `response_file_path` calls
    to reduce per-token processing overhead.
    """
    cleaned = token.strip().strip('"')
    if cleaned.startswith('@') and len(cleaned) > 1:
        path = response_file_path(cleaned)
        name = path.name if path else cleaned
    else:
        name = cleaned

    lower_name = name.lower()

    start = 0
    while True:
        obj_idx = lower_name.find('.obj', start)
        if obj_idx <= 0:
            return None

        if '/' in lower_name[start:obj_idx] or '\\' in lower_name[start:obj_idx]:
            return None

        if len(lower_name) == obj_idx + 4 or lower_name[obj_idx + 4] == '.':
            return lower_name[:obj_idx + 4]

        start = obj_idx + 4


def makefile_logical_lines(text: str) -> List[str]:
    logical: List[str] = []
    buffer = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            if buffer:
                logical.append(buffer.strip())
                buffer = ""
            continue
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        if buffer:
            line = buffer + line
            buffer = ""
        logical.append(line.strip())
    if buffer.strip():
        logical.append(buffer.strip())
    return logical


def makefile_object_source_map(
    makefile_path: Path,
    extensions: Iterable[str],
) -> Dict[str, str]:
    if not makefile_path.exists():
        return {}
    mapping: Dict[str, str] = {}
    extension_set = {ext.lower() for ext in extensions}
    for line in makefile_logical_lines(read_text_lossy(makefile_path)):
        if ":" not in line:
            continue
        target_part, dependency_part = line.split(":", 1)
        if ".obj" not in target_part.lower():
            continue
        target_tokens = split_windows_args(target_part)
        dependency_tokens = split_windows_args(dependency_part)
        source_token = next(
            (
                token
                for token in dependency_tokens
                if Path(token.strip().strip('"')).suffix.lower() in extension_set
            ),
            None,
        )
        if not source_token:
            continue
        for target_token in target_tokens:
            cleaned_target = target_token.strip().strip('"')
            if Path(cleaned_target).suffix.lower() != ".obj":
                continue
            mapping[Path(cleaned_target).name.lower()] = source_token
    return mapping


def mapped_sources_from_response_tokens(
    tokens: Sequence[str],
    object_source_map: Dict[str, str],
) -> List[str]:
    sources: List[str] = []
    seen = set()
    for token in tokens:
        key = object_key_from_token(token)
        if not key:
            continue
        source = object_source_map.get(key)
        if not source:
            continue
        normalized = source.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        sources.append(source)
    return sources


CL_RE = re.compile(
    r'(?i)(?:"[^"]*\\cl(?:\.exe)?"|(?:^|[\s&])(?:cl|cl\.exe)(?=\s))'
)


def extract_cl_command(line: str) -> Optional[str]:
    match = CL_RE.search(line)
    if not match:
        return None
    start = match.start()
    while start < len(line) and line[start] in " &":
        start += 1
    command = line[start:].strip()
    lowered = command.lower()
    if "/c" not in lowered and " -c " not in lowered:
        return None
    return command


def is_source_file_token(token: str, extensions: tuple[str, ...]) -> bool:
    cleaned = token.strip().strip('"')
    lowered = cleaned.lower()
    if lowered.startswith("/") or lowered.startswith("-"):
        return False
    return lowered.endswith(extensions)


def resolve_source_path(token: str, command_dir: Path, source_root: Path) -> Path:
    cleaned = token.strip().strip('"')
    candidate = Path(cleaned)
    if candidate.is_absolute():
        return candidate.resolve()
    build_relative = (command_dir / candidate).resolve()
    if build_relative.exists():
        return build_relative
    return (source_root / candidate).resolve()


def compile_db_from_build_log(
    log_text: str,
    command_dir: Path,
    source_root: Path,
    extensions: Iterable[str],
    response_archive_dir: Optional[Path] = None,
    object_source_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    entries: List[Dict[str, str]] = []
    warnings: List[str] = []
    seen = set()
    extension_tuple = tuple(ext.lower() for ext in extensions)

    for line in normalize_make_output(log_text):
        cl_command = extract_cl_command(line)
        if not cl_command:
            continue
        raw_tokens = split_windows_args(cl_command)
        tokens = expand_response_files(
            raw_tokens,
            command_dir,
            response_archive_dir,
            warnings,
        )
        sources = [token for token in tokens if is_source_file_token(token, extension_tuple)]
        if not sources and object_source_map:
            sources = mapped_sources_from_response_tokens(raw_tokens, object_source_map)
            if sources:
                tokens = [token for token in tokens if response_file_path(token) is None]
                tokens.extend(sources)
        if not sources:
            warnings.append(f"Skipped cl command without source file: {line[:240]}")
            continue
        expanded_command = windows_cmdline(tokens)
        for source_token in sources:
            source_path = resolve_source_path(source_token, command_dir, source_root)
            key = (str(source_path).lower(), expanded_command)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "directory": str(command_dir),
                    "command": expanded_command,
                    "file": str(source_path),
                }
            )

    return entries, warnings


def parse_compile_entries_from_log_file(
    log_paths: Sequence[str],
    command_dir: Path,
    source_root: Path,
    extensions: Iterable[str],
    response_archive_dir: Optional[Path] = None,
    object_source_map: Optional[Dict[str, str]] = None,
) -> Tuple[List[Dict[str, str]], List[str]]:
    log_text = "\n".join(read_text_lossy(Path(path)) for path in log_paths if Path(path).exists())
    return compile_db_from_build_log(
        log_text,
        command_dir,
        source_root,
        extensions,
        response_archive_dir=response_archive_dir,
        object_source_map=object_source_map,
    )


def load_compile_database(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"compile_commands.json must be a list: {path}")
    return data


def source_files_from_compile_db(
    entries: Sequence[Dict[str, str]],
    extensions: Iterable[str],
) -> List[Path]:
    allowed = {ext.lower() for ext in extensions}
    files: List[Path] = []
    seen = set()
    for entry in entries:
        raw_file = entry.get("file", "")
        if not raw_file:
            continue
        path = Path(raw_file)
        if path.suffix.lower() not in allowed:
            continue
        if not path.is_absolute():
            path = (Path(entry.get("directory", ".")) / path).resolve()
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    return files


CLANG_DIAG_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s+"
    r"(?P<severity>warning|error|note):\s+"
    r"(?P<message>.*?)(?:\s+\[(?P<rule>[^\]]+)\])?$"
)


def parse_clang_tidy_output(text: str) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for line in text.splitlines():
        match = CLANG_DIAG_RE.match(line.strip())
        if not match:
            continue
        if match.group("severity") == "note":
            continue
        issues.append(
            {
                "analyzer": "clang-tidy",
                "severity": match.group("severity"),
                "file": str(Path(match.group("file")).resolve()),
                "line": int(match.group("line")),
                "column": int(match.group("column")),
                "rule": match.group("rule") or "clang-tidy",
                "message": match.group("message").strip(),
            }
        )
    return issues


def run_clang_tidy(
    cfg: Dict[str, Any],
    compile_db: Path,
    source_files: Sequence[Path],
    output_dir: Path,
    env: Dict[str, str],
    vcvars: str,
    config_dir: Optional[Path],
) -> Tuple[List[Dict[str, Any]], List[CommandResult], List[str]]:
    settings = cfg["analysis"]["clangTidy"]
    executable = resolve_executable(settings["path"], config_dir)
    warnings: List[str] = []
    results: List[CommandResult] = []
    issues: List[Dict[str, Any]] = []

    if not executable_exists(executable):
        message = f"clang-tidy not found: {executable}"
        if cfg["analysis"].get("failOnMissingTool"):
            raise FileNotFoundError(message)
        warnings.append(message)
        return issues, results, warnings

    jobs = max(int(settings.get("jobs", 1)), 1)
    log_root = output_dir / "logs" / "clang-tidy"
    log_root.mkdir(parents=True, exist_ok=True)

    def run_one(index_and_file: Tuple[int, Path]) -> Tuple[List[Dict[str, Any]], CommandResult]:
        index, source = index_and_file
        command = [
            executable,
            str(source),
            "-p",
            str(compile_db.parent),
            f"--checks={settings.get('checks', '')}",
            f"--header-filter={settings.get('headerFilter', '.*')}",
        ]
        command.extend(str(arg) for arg in settings.get("extraArgs", []))
        result = run_command(
            f"clang-tidy-{index:04d}",
            command,
            compile_db.parent,
            log_root,
            env_overrides=env,
            vcvars=vcvars,
        )
        text = read_text_lossy(Path(result.stdout_path)) + "\n" + read_text_lossy(Path(result.stderr_path))
        return parse_clang_tidy_output(text), result

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for file_issues, command_result in pool.map(run_one, enumerate(source_files, start=1)):
            issues.extend(file_issues)
            results.append(command_result)

    return issues, results, warnings


def parse_cppcheck_xml(path: Path) -> List[Dict[str, Any]]:
    if not path.exists() or not path.read_text(encoding="utf-8", errors="replace").strip():
        return []
    root = ET.parse(path).getroot()
    issues: List[Dict[str, Any]] = []
    for error in root.findall(".//error"):
        severity = error.attrib.get("severity", "unknown")
        rule = error.attrib.get("id", "cppcheck")
        message = error.attrib.get("msg") or error.attrib.get("verbose") or ""
        locations = error.findall("location")
        if not locations:
            issues.append(
                {
                    "analyzer": "cppcheck",
                    "severity": severity,
                    "file": "",
                    "line": 0,
                    "column": 0,
                    "rule": rule,
                    "message": message,
                }
            )
            continue
        for location in locations[:1]:
            issues.append(
                {
                    "analyzer": "cppcheck",
                    "severity": severity,
                    "file": str(Path(location.attrib.get("file", "")).resolve())
                    if location.attrib.get("file")
                    else "",
                    "line": int(location.attrib.get("line", "0") or "0"),
                    "column": int(location.attrib.get("column", "0") or "0"),
                    "rule": rule,
                    "message": message,
                }
            )
    return issues


def run_cppcheck(
    cfg: Dict[str, Any],
    compile_db: Path,
    output_dir: Path,
    env: Dict[str, str],
    vcvars: str,
    config_dir: Optional[Path],
) -> Tuple[List[Dict[str, Any]], List[CommandResult], List[str]]:
    settings = cfg["analysis"]["cppcheck"]
    executable = resolve_executable(settings["path"], config_dir)
    warnings: List[str] = []
    results: List[CommandResult] = []

    if not executable_exists(executable):
        message = f"cppcheck not found: {executable}"
        if cfg["analysis"].get("failOnMissingTool"):
            raise FileNotFoundError(message)
        warnings.append(message)
        return [], results, warnings

    xml_path = output_dir / "cppcheck.xml"
    command = [
        executable,
        f"--project={compile_db}",
        f"--enable={settings.get('enable', 'all')}",
        "--xml",
        "--xml-version=2",
        f"--output-file={xml_path}",
    ]
    if settings.get("inconclusive", False):
        command.append("--inconclusive")
    for suppression in settings.get("suppressions", []):
        command.append(f"--suppress={suppression}")
    command.extend(str(arg) for arg in settings.get("extraArgs", []))

    result = run_command(
        "cppcheck",
        command,
        compile_db.parent,
        output_dir / "logs",
        env_overrides=env,
        vcvars=vcvars,
    )
    results.append(result)
    return parse_cppcheck_xml(xml_path), results, warnings


def snippet_for_file(
    path: Path,
    line: int,
    context_lines: int,
    file_cache: Optional[Dict[Path, List[str]]] = None,
) -> List[Dict[str, Any]]:
    if not path.exists() or line <= 0:
        return []

    if file_cache is not None:
        if path not in file_cache:
            file_cache[path] = read_text_lossy(path).splitlines()
        lines = file_cache[path]
    else:
        lines = read_text_lossy(path).splitlines()

    start = max(1, line - context_lines)
    end = min(len(lines), line + context_lines)
    snippet: List[Dict[str, Any]] = []
    for number in range(start, end + 1):
        snippet.append(
            {
                "line": number,
                "text": lines[number - 1],
                "target": number == line,
            }
        )
    return snippet


def attach_snippets(
    issues: List[Dict[str, Any]],
    include: bool,
    context_lines: int,
) -> None:
    if not include:
        return

    file_cache: Dict[Path, List[str]] = {}
    for issue in issues:
        file_name = issue.get("file") or ""
        if not file_name:
            issue["snippet"] = []
            continue
        issue["snippet"] = snippet_for_file(
            Path(file_name),
            int(issue.get("line") or 0),
            context_lines,
            file_cache
        )


def _norm_path_prefix(path: Path) -> str:
    # Case-insensitive, separator-normalized prefix for Windows-friendly comparisons.
    return os.path.normcase(os.path.normpath(str(path.resolve())))


def resolve_filter_roots(
    raw_paths: Sequence[str],
    base_dir: Path,
    config_dir: Optional[Path],
) -> List[str]:
    resolved: List[str] = []
    for raw in raw_paths:
        if not raw:
            continue
        expanded = os.path.expandvars(os.path.expanduser(str(raw)))
        candidate = Path(expanded)
        if candidate.is_absolute():
            resolved.append(_norm_path_prefix(candidate))
            continue
        if config_dir and (config_dir / candidate).exists():
            resolved.append(_norm_path_prefix((config_dir / candidate).resolve()))
            continue
        resolved.append(_norm_path_prefix((base_dir / candidate).resolve()))
    return resolved


def filter_issues_by_paths(
    issues: List[Dict[str, Any]],
    include_roots: Sequence[str],
    exclude_roots: Sequence[str],
) -> List[Dict[str, Any]]:
    if not include_roots and not exclude_roots:
        return issues

    include = [root.rstrip("\\/") for root in include_roots if root]
    exclude = [root.rstrip("\\/") for root in exclude_roots if root]

    filtered: List[Dict[str, Any]] = []
    for issue in issues:
        file_name = str(issue.get("file") or "").strip()
        if not file_name:
            filtered.append(issue)
            continue

        try:
            file_norm = _norm_path_prefix(Path(file_name))
        except OSError:
            filtered.append(issue)
            continue

        if exclude and any(file_norm.startswith(root) for root in exclude):
            continue
        if include and not any(file_norm.startswith(root) for root in include):
            continue

        filtered.append(issue)

    return filtered


def issue_sort_key(issue: Dict[str, Any]) -> Tuple[str, str, int, int, str]:
    return (
        issue.get("file") or "",
        issue.get("analyzer") or "",
        int(issue.get("line") or 0),
        int(issue.get("column") or 0),
        issue.get("rule") or "",
    )


def summarize_issues(issues: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "total": len(issues),
        "byAnalyzer": {},
        "bySeverity": {},
    }
    for issue in issues:
        analyzer = issue.get("analyzer", "unknown")
        severity = issue.get("severity", "unknown")
        summary["byAnalyzer"][analyzer] = summary["byAnalyzer"].get(analyzer, 0) + 1
        summary["bySeverity"][severity] = summary["bySeverity"].get(severity, 0) + 1
    return summary


def render_snippet(snippet: Sequence[Dict[str, Any]]) -> str:
    if not snippet:
        return '<span class="muted">No snippet available.</span>'
    rows = []
    for item in snippet:
        css = "target" if item.get("target") else ""
        rows.append(
            '<div class="{css}"><span class="line-no">{line}</span>{text}</div>'.format(
                css=css,
                line=html.escape(str(item.get("line", ""))),
                text=html.escape(str(item.get("text", ""))),
            )
        )
    return "\n".join(rows)


def format_generated_at_tr_eu(iso_timestamp: str) -> str:
    """
    Format ISO timestamps (e.g. 2026-05-08T11:28:00+03:00) into TR/EU style:
    DD.MM.YYYY HH:MM:SS UTC±HH:MM
    """
    raw = (iso_timestamp or "").strip()
    if not raw:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return raw
    local = parsed.astimezone() if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc).astimezone()
    offset = local.utcoffset() or dt.timedelta()
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hh = total_minutes // 60
    mm = total_minutes % 60
    return f"{local:%d.%m.%Y %H:%M:%S} UTC{sign}{hh:02d}:{mm:02d}"


def load_rule_docs(
    cfg: Dict[str, Any],
    config_dir: Optional[Path],
    base_dir: Optional[Path] = None,
) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], List[str]]:
    """
    Load offline rule documentation from one or more JSON files.

    Expected JSON format:
      {
        "analyzer": "clang-tidy",
        "rules": {
          "modernize-use-trailing-return-type": {
            "title": "...",
            "summary": "...",
            "why": "...",
            "exampleBefore": "...",
            "exampleAfter": "...",
            "notes": ["..."]
          }
        }
      }
    """
    warnings: List[str] = []
    mapping: Dict[Tuple[str, str], Dict[str, Any]] = {}
    report_cfg = cfg.get("report", {}) or {}
    rule_cfg = report_cfg.get("ruleDocs", {}) or {}
    raw_paths = rule_cfg.get("paths", []) or []
    if not raw_paths:
        return mapping, warnings

    root = base_dir or Path.cwd()
    for raw in raw_paths:
        doc_path = resolve_optional_path(str(raw), root, config_dir)
        if not doc_path or not doc_path.exists():
            continue
        try:
            payload = json.loads(read_text_lossy(doc_path))
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"Failed to load rule docs {doc_path}: {exc}")
            continue
        analyzer = str(payload.get("analyzer", "") or "").strip()
        rules = payload.get("rules", {})
        if not analyzer or not isinstance(rules, dict):
            warnings.append(f"Invalid rule docs file (missing analyzer/rules): {doc_path}")
            continue
        for rule_id, info in rules.items():
            if not rule_id:
                continue
            if not isinstance(info, dict):
                continue
            mapping[(analyzer, str(rule_id))] = info
    return mapping, warnings


def attach_rule_docs(
    issues: List[Dict[str, Any]],
    rule_docs: Dict[Tuple[str, str], Dict[str, Any]],
) -> None:
    if not rule_docs:
        return
    for issue in issues:
        analyzer = str(issue.get("analyzer") or "").strip()
        rule = str(issue.get("rule") or "").strip()
        if not analyzer or not rule:
            continue
        info = rule_docs.get((analyzer, rule))
        if info:
            issue["ruleInfo"] = info


def render_html_report(report: Dict[str, Any]) -> str:
    generated = html.escape(format_generated_at_tr_eu(str(report["metadata"]["generatedAt"])))
    project = html.escape(report["metadata"].get("project", ""))
    summary = report["summary"]
    issues = report["issues"]
    tool_results = report.get("toolResults", [])
    warnings = report.get("warnings", [])

    issue_rows = []
    for index, issue in enumerate(issues, start=1):
        severity = html.escape(str(issue.get("severity", "unknown")))
        analyzer = html.escape(str(issue.get("analyzer", "unknown")))
        rule = html.escape(str(issue.get("rule", "")))
        file_name = html.escape(str(issue.get("file", "")))
        line = html.escape(str(issue.get("line", "")))
        column = html.escape(str(issue.get("column", "")))
        message = html.escape(str(issue.get("message", "")))
        snippet = render_snippet(issue.get("snippet", []))
        rule_info = issue.get("ruleInfo") or {}
        rule_title = html.escape(str(rule_info.get("title", ""))) if isinstance(rule_info, dict) else ""
        rule_summary = html.escape(str(rule_info.get("summary", ""))) if isinstance(rule_info, dict) else ""
        rule_why = html.escape(str(rule_info.get("why", ""))) if isinstance(rule_info, dict) else ""
        example_before = str(rule_info.get("exampleBefore", "")) if isinstance(rule_info, dict) else ""
        example_after = str(rule_info.get("exampleAfter", "")) if isinstance(rule_info, dict) else ""
        notes = rule_info.get("notes", []) if isinstance(rule_info, dict) else []
        if not isinstance(notes, list):
            notes = []
        notes_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in notes) if notes else ""
        rule_block = ""
        if rule_title or rule_summary or rule_why or example_before or example_after or notes_html:
            rule_block = f"""
              <details>
                <summary>Rule info</summary>
                <div class="panel" style="margin-top:10px;">
                  {f"<p><strong>{rule_title}</strong></p>" if rule_title else ""}
                  {f"<p>{rule_summary}</p>" if rule_summary else ""}
                  {f"<p class='muted'>{rule_why}</p>" if rule_why else ""}
                  {f"<p><strong>Before</strong></p><pre>{html.escape(example_before)}</pre>" if example_before else ""}
                  {f"<p><strong>After</strong></p><pre>{html.escape(example_after)}</pre>" if example_after else ""}
                  {f"<ul>{notes_html}</ul>" if notes_html else ""}
                </div>
              </details>
            """
        issue_rows.append(
            f"""
            <article class="issue">
              <header>
                <span class="badge {severity}">{severity}</span>
                <strong>{analyzer}</strong>
                <code>{rule}</code>
              </header>
              <p>{message}</p>
              <div class="location"><code>{file_name}:{line}:{column}</code></div>
              <details>
                <summary>Source snippet</summary>
                <pre>{snippet}</pre>
              </details>
              {rule_block}
            </article>
            """
        )

    if not issue_rows:
        issue_rows.append('<p class="empty">No findings were reported by the enabled analyzers.</p>')

    warning_rows = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings)
    if not warning_rows:
        warning_rows = "<li>No warnings.</li>"

    tool_rows = []
    for result in tool_results:
        command = html.escape(windows_cmdline(result.get("command", [])))
        tool_rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('tool', '')))}</td>"
            f"<td>{html.escape(str(result.get('exit_code', '')))}</td>"
            f"<td>{html.escape(str(result.get('duration_seconds', '')))}s</td>"
            f"<td><code>{command}</code></td>"
            "</tr>"
        )
    if not tool_rows:
        tool_rows.append('<tr><td colspan="4">No external tools were executed.</td></tr>')

    severity_items = "".join(
        f"<li><strong>{html.escape(str(name))}</strong>: {count}</li>"
        for name, count in sorted(summary["bySeverity"].items())
    )
    analyzer_items = "".join(
        f"<li><strong>{html.escape(str(name))}</strong>: {count}</li>"
        for name, count in sorted(summary["byAnalyzer"].items())
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cpplyzer Report</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1c2027;
      --muted: #667085;
      --line: #d7dce2;
      --accent: #2457a6;
      --error: #b42318;
      --warning: #b54708;
      --style: #175cd3;
      --info: #345c46;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    h1, h2 {{ margin: 0 0 12px; letter-spacing: 0; }}
    h1 {{ font-size: 32px; }}
    h2 {{ font-size: 20px; margin-top: 28px; }}
    .meta, .muted {{ color: var(--muted); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin: 24px 0;
    }}
    .panel, .issue {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .count {{
      display: block;
      font-size: 34px;
      font-weight: 700;
      color: var(--accent);
    }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    .issue {{ margin: 12px 0; }}
    .issue header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }}
    .badge {{
      display: inline-block;
      border-radius: 4px;
      padding: 2px 7px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .error {{ background: var(--error); }}
    .warning {{ background: var(--warning); }}
    .style, .performance, .portability {{ background: var(--style); }}
    .information, .info, .unknown {{ background: var(--info); }}
    code, pre {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
    }}
    code {{
      overflow-wrap: anywhere;
    }}
    .location {{
      color: var(--muted);
      margin-bottom: 10px;
    }}
    details {{
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 10px;
    }}
    summary {{ cursor: pointer; color: var(--accent); }}
    pre {{
      margin: 10px 0 0;
      padding: 12px;
      background: #101828;
      color: #f2f4f7;
      overflow-x: auto;
      border-radius: 6px;
    }}
    pre div {{ white-space: pre; }}
    .line-no {{
      display: inline-block;
      width: 54px;
      color: #98a2b3;
      user-select: none;
    }}
    .target {{
      background: rgba(255, 196, 0, 0.18);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #eef2f6; }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Cpplyzer Report</h1>
    <p class="meta">Project: <code>{project}</code><br>Generated: {generated}</p>

    <section class="summary">
      <div class="panel">
        <span class="count">{summary["total"]}</span>
        Total findings
      </div>
      <div class="panel">
        <strong>By severity</strong>
        <ul>{severity_items or "<li>No findings.</li>"}</ul>
      </div>
      <div class="panel">
        <strong>By analyzer</strong>
        <ul>{analyzer_items or "<li>No findings.</li>"}</ul>
      </div>
    </section>

    <h2>Findings</h2>
    {''.join(issue_rows)}

    <h2>Warnings</h2>
    <div class="panel"><ul>{warning_rows}</ul></div>

    <h2>Tool Runs</h2>
    <table>
      <thead><tr><th>Tool</th><th>Exit</th><th>Duration</th><th>Command</th></tr></thead>
      <tbody>{''.join(tool_rows)}</tbody>
    </table>
  </main>
</body>
</html>
"""


def command_result_to_dict(result: CommandResult) -> Dict[str, Any]:
    return {
        "tool": result.tool,
        "command": result.command,
        "cwd": result.cwd,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "stdout_path": result.stdout_path,
        "stderr_path": result.stderr_path,
    }


def apply_cli_overrides(cfg: Dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "qmake", None):
        cfg["toolchain"]["qmake"] = args.qmake
    if getattr(args, "jom", None):
        cfg["toolchain"]["jom"] = args.jom
    if getattr(args, "clang_tidy", None):
        cfg["analysis"]["clangTidy"]["path"] = args.clang_tidy
    if getattr(args, "cppcheck", None):
        cfg["analysis"]["cppcheck"]["path"] = args.cppcheck
    if getattr(args, "strict_tools", False):
        cfg["analysis"]["failOnMissingTool"] = True
    if getattr(args, "skip_clang_tidy", False):
        cfg["analysis"]["clangTidy"]["enabled"] = False
    if getattr(args, "skip_cppcheck", False):
        cfg["analysis"]["cppcheck"]["enabled"] = False


def relative_display_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def project_slug(project_file: Path, root: Path) -> str:
    relative = relative_display_path(project_file, root)
    without_suffix = str(Path(relative).with_suffix(""))
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "__", without_suffix)
    return slug.strip("._-") or project_file.stem


def discover_pro_files(root: Path, cfg: Dict[str, Any]) -> List[Path]:
    ignore_dirs = {name.lower() for name in cfg.get("discovery", {}).get("ignoreDirs", [])}
    ignore_names = {name.lower() for name in cfg.get("discovery", {}).get("ignoreProNames", [])}
    projects: List[Path] = []
    for current_root, dir_names, file_names in os.walk(root):
        dir_names[:] = [
            name for name in dir_names
            if name.lower() not in ignore_dirs
        ]
        for file_name in file_names:
            if not file_name.lower().endswith(".pro"):
                continue
            if file_name.lower() in ignore_names:
                continue
            projects.append((Path(current_root) / file_name).resolve())
    projects.sort(key=lambda path: str(path).lower())
    return projects


def capture_compile_commands(
    project_file: Path,
    build_dir: Path,
    output_dir: Path,
    cfg: Dict[str, Any],
    config_dir: Optional[Path],
) -> Tuple[Path, List[CommandResult], List[str]]:
    build_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    env = cfg["build"].get("environment", {})
    vcvars = resolve_executable(cfg["toolchain"].get("vcvars", ""), config_dir)
    qmake = resolve_executable(cfg["toolchain"].get("qmake", "qmake"), config_dir)
    jom = resolve_executable(cfg["toolchain"].get("jom", "jom"), config_dir)
    command_results: List[CommandResult] = []
    warnings: List[str] = []

    if not cfg["build"].get("skipQmake", False):
        qmake_command = [qmake, str(project_file)]
        qmake_command.extend(str(arg) for arg in cfg["build"].get("qmakeArgs", []))
        eprint(f"Running qmake: {windows_cmdline(qmake_command)}")
        qmake_result = run_command("qmake", qmake_command, build_dir, logs_dir, env, vcvars)
        command_results.append(qmake_result)
        if qmake_result.exit_code != 0:
            raise RuntimeError(command_failure_message(qmake_result, "qmake"))

    jom_command = [jom]
    jom_command.extend(str(arg) for arg in cfg["build"].get("jomDryRunArgs", []))
    eprint(f"Running jom dry-run for build capture: {windows_cmdline(jom_command)}")
    jom_result = run_command("jom-dry-run", jom_command, build_dir, logs_dir, env, vcvars)
    command_results.append(jom_result)
    if jom_result.exit_code != 0:
        warnings.append(command_failure_message(jom_result, "jom dry-run"))

    extensions = cfg["analysis"].get("sourceExtensions", list(SOURCE_EXTENSIONS))
    log_text = read_text_lossy(Path(jom_result.stdout_path)) + "\n" + read_text_lossy(Path(jom_result.stderr_path))
    entries, parse_warnings = compile_db_from_build_log(
        log_text,
        build_dir,
        project_file.parent,
        extensions,
        response_archive_dir=logs_dir / "response-files",
    )
    warnings.extend(parse_warnings[:50])

    if not entries:
        fallback_entries, fallback_results, fallback_warnings = fallback_makefile_capture(
            jom,
            log_text,
            project_file,
            build_dir,
            output_dir,
            cfg,
            env,
            vcvars,
        )
        entries.extend(fallback_entries)
        command_results.extend(fallback_results)
        warnings.extend(fallback_warnings)

    if not entries:
        warning_excerpt = warnings[:30]
        if warning_excerpt:
            (logs_dir / "capture-warnings.txt").write_text(
                "\n".join(warning_excerpt) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        (logs_dir / "capture-help.txt").write_text(
            "\n".join(
                [
                    "No MSVC compile commands were captured.",
                    "",
                    "The top-level jom dry-run may only print a recursive make command such as:",
                    "  jom.exe -f Makefile.Release",
                    "",
                    "Try one of these options:",
                    '  1. Set build.jomDryRunArgs to ["-n", "-f", "Makefile.Release"].',
                    "  2. Run a normal build with visible cl.exe commands and pass --build-log.",
                    "  3. Provide an existing compile_commands.json with --compile-commands.",
                    "",
                    "Recent parser warnings:",
                    *(warning_excerpt or ["  none"]),
                ]
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        warning_note = ""
        if warning_excerpt:
            warning_note = " Parser warnings: " + " | ".join(warning_excerpt[:5])
        raise RuntimeError(
            "No MSVC compile commands were captured. Try setting build.jomDryRunArgs "
            'to ["-n", "-f", "Makefile.Release"], pass --build-log from a real build, '
            "or pass --compile-commands. See capture-help.txt in the project logs."
            + warning_note
        )

    compile_db = build_dir / "compile_commands.json"
    write_json(compile_db, entries)
    return compile_db, command_results, warnings


def compile_commands_from_existing_log(
    build_log: Path,
    project_file: Path,
    build_dir: Path,
    cfg: Dict[str, Any],
) -> Tuple[Path, List[str]]:
    log_text = read_text_lossy(build_log)
    entries, warnings = compile_db_from_build_log(
        log_text,
        build_dir,
        project_file.parent,
        cfg["analysis"].get("sourceExtensions", list(SOURCE_EXTENSIONS)),
        response_archive_dir=build_dir / "response-files",
    )
    if not entries:
        raise RuntimeError(f"No MSVC compile commands were found in build log: {build_log}")
    compile_db = build_dir / "compile_commands.json"
    build_dir.mkdir(parents=True, exist_ok=True)
    write_json(compile_db, entries)
    return compile_db, warnings


def makefile_candidates_from_log(log_text: str, build_dir: Path, cfg: Dict[str, Any]) -> List[str]:
    observed: List[str] = []
    observed_seen = set()
    for match in re.finditer(r"(?i)-f\s+([^\s\"']*Makefile(?:\.[A-Za-z0-9_.-]+)?)", log_text):
        name = match.group(1).strip().strip('"').strip("'")
        if not name:
            continue
        path = Path(name)
        if path.is_absolute():
            exists = path.exists()
            candidate = str(path)
            key = candidate.lower()
        else:
            exists = (build_dir / path).exists()
            candidate = str(path)
            key = candidate.lower()
        if exists and key not in observed_seen:
            observed_seen.add(key)
            observed.append(candidate)

    if observed:
        return observed

    candidates: List[str] = []
    seen = set()
    for name in cfg["build"].get("fallbackMakefiles", []):
        if name and (build_dir / name).exists():
            key = name.lower()
            if key not in seen:
                seen.add(key)
                candidates.append(name)

    return candidates


def fallback_makefile_capture(
    jom: str,
    initial_log_text: str,
    project_file: Path,
    build_dir: Path,
    output_dir: Path,
    cfg: Dict[str, Any],
    env: Dict[str, str],
    vcvars: str,
) -> Tuple[List[Dict[str, str]], List[CommandResult], List[str]]:
    warnings: List[str] = []
    results: List[CommandResult] = []
    entries: List[Dict[str, str]] = []
    extensions = cfg["analysis"].get("sourceExtensions", list(SOURCE_EXTENSIONS))
    candidates = makefile_candidates_from_log(initial_log_text, build_dir, cfg)

    if not candidates:
        warnings.append(
            "No compile commands were found in the top-level dry-run output, and no "
            "Makefile.Release/Makefile.Debug fallback was available."
        )
        return entries, results, warnings

    for index, makefile_name in enumerate(candidates, start=1):
        makefile_path = Path(makefile_name)
        if not makefile_path.is_absolute():
            makefile_path = build_dir / makefile_path
        object_source_map = makefile_object_source_map(makefile_path, extensions)
        if object_source_map:
            warnings.append(
                f"Loaded {len(object_source_map)} object/source mapping(s) from {makefile_path.name}."
            )
        command = [jom, "-n", "-f", makefile_name]
        eprint(f"Running fallback jom dry-run: {windows_cmdline(command)}")
        result = run_command(
            f"jom-dry-run-fallback-{index}",
            command,
            build_dir,
            output_dir / "logs",
            env,
            vcvars,
        )
        results.append(result)
        if result.exit_code != 0:
            warnings.append(command_failure_message(result, f"fallback jom dry-run ({makefile_name})"))
            continue

        parsed, parse_warnings = parse_compile_entries_from_log_file(
            [result.stdout_path, result.stderr_path],
            build_dir,
            project_file.parent,
            extensions,
            response_archive_dir=output_dir / "logs" / "response-files",
            object_source_map=object_source_map,
        )
        warnings.extend(parse_warnings[:50])
        entries.extend(parsed)

    return entries, results, warnings


def generate_report(
    project_file: Path,
    compile_db: Path,
    issues: List[Dict[str, Any]],
    tool_results: List[CommandResult],
    warnings: List[str],
    output_dir: Path,
) -> Dict[str, Any]:
    issues.sort(key=issue_sort_key)
    report = {
        "metadata": {
            "tool": "Cpplyzer",
            "version": VERSION,
            "generatedAt": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
            "project": str(project_file),
            "compileCommands": str(compile_db),
        },
        "summary": summarize_issues(issues),
        "warnings": warnings,
        "toolResults": [command_result_to_dict(result) for result in tool_results],
        "issues": issues,
    }
    write_json(output_dir / "cpplyzer-report.json", report)
    html_text = render_html_report(report)
    (output_dir / "cpplyzer-report.html").write_text(html_text, encoding="utf-8", newline="\n")
    return report


def run_analysis_for_project(
    project_file: Path,
    cfg: Dict[str, Any],
    config_dir: Optional[Path],
    output_dir: Path,
    build_dir: Path,
    compile_commands_override: str = "",
    build_log_override: str = "",
) -> Dict[str, Any]:
    project_file = project_file.resolve()
    if not project_file.exists():
        raise FileNotFoundError(f"Project file not found: {project_file}")
    if project_file.suffix.lower() != ".pro":
        raise ValueError(f"Expected a Qt .pro file, got: {project_file}")

    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    warnings: List[str] = []
    tool_results: List[CommandResult] = []
    rule_docs, rule_doc_warnings = load_rule_docs(cfg, config_dir, base_dir=project_file.parent)
    warnings.extend(rule_doc_warnings)

    compile_db_override = compile_commands_override or cfg["analysis"].get("compileCommands", "")
    compile_db_path = resolve_optional_path(compile_db_override, Path.cwd(), config_dir)
    if compile_db_path:
        if not compile_db_path.exists():
            raise FileNotFoundError(f"compile_commands.json not found: {compile_db_path}")
        compile_db = compile_db_path.resolve()
    elif build_log_override:
        build_log = Path(build_log_override).resolve()
        if not build_log.exists():
            raise FileNotFoundError(f"Build log not found: {build_log}")
        compile_db, log_warnings = compile_commands_from_existing_log(
            build_log,
            project_file,
            build_dir,
            cfg,
        )
        warnings.extend(log_warnings)
    else:
        compile_db, capture_results, capture_warnings = capture_compile_commands(
            project_file,
            build_dir,
            output_dir,
            cfg,
            config_dir,
        )
        tool_results.extend(capture_results)
        warnings.extend(capture_warnings)

    compile_entries = load_compile_database(compile_db)
    source_files = source_files_from_compile_db(
        compile_entries,
        cfg["analysis"].get("sourceExtensions", list(SOURCE_EXTENSIONS)),
    )
    if not source_files:
        warnings.append(f"No source files found in compile database: {compile_db}")

    env = cfg["build"].get("environment", {})
    vcvars = resolve_executable(cfg["toolchain"].get("vcvars", ""), config_dir)
    issues: List[Dict[str, Any]] = []

    if cfg["analysis"]["clangTidy"].get("enabled", True) and source_files:
        eprint(f"Running clang-tidy on {len(source_files)} source file(s)...")
        found, results, tool_warnings = run_clang_tidy(
            cfg,
            compile_db,
            source_files,
            output_dir,
            env,
            vcvars,
            config_dir,
        )
        issues.extend(found)
        tool_results.extend(results)
        warnings.extend(tool_warnings)

    if cfg["analysis"]["cppcheck"].get("enabled", True):
        eprint("Running cppcheck...")
        found, results, tool_warnings = run_cppcheck(cfg, compile_db, output_dir, env, vcvars, config_dir)
        issues.extend(found)
        tool_results.extend(results)
        warnings.extend(tool_warnings)

    # Filter out issues that belong to toolchain/SDK headers (e.g. C:\Qt\...),
    # unless the user explicitly includes those roots in report.pathFilters.
    filter_cfg = cfg.get("report", {}).get("pathFilters", {}) or {}
    raw_includes = filter_cfg.get("includeRoots", []) or []
    raw_excludes = filter_cfg.get("excludeRoots", []) or []
    base_dir = Path.cwd()
    include_roots = resolve_filter_roots(raw_includes, base_dir, config_dir)
    exclude_roots = resolve_filter_roots(raw_excludes, base_dir, config_dir)
    if not include_roots:
        include_roots = [_norm_path_prefix(project_file.parent)]
    before_count = len(issues)
    issues = filter_issues_by_paths(issues, include_roots, exclude_roots)
    removed = before_count - len(issues)
    if removed:
        warnings.append(
            f"Filtered {removed} issue(s) outside included roots. "
            f"includeRoots={len(include_roots)} excludeRoots={len(exclude_roots)}"
        )

    attach_rule_docs(issues, rule_docs)

    max_issues = int(cfg["report"].get("maxIssues", 10000))
    if len(issues) > max_issues:
        warnings.append(f"Issue list truncated from {len(issues)} to {max_issues}.")
        issues = issues[:max_issues]

    attach_snippets(
        issues,
        bool(cfg["report"].get("includeSnippets", True)),
        int(cfg["report"].get("contextLines", 2)),
    )
    report = generate_report(project_file, compile_db, issues, tool_results, warnings, output_dir)
    return report


def analyze(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve() if args.config else None
    cfg, config_dir = load_config(config_path)
    apply_cli_overrides(cfg, args)

    project_file = Path(args.project).resolve()
    output_dir = Path(args.output).resolve()
    build_dir = Path(args.build_dir).resolve()
    report = run_analysis_for_project(
        project_file,
        cfg,
        config_dir,
        output_dir,
        build_dir,
        compile_commands_override=args.compile_commands or "",
        build_log_override=args.build_log or "",
    )
    eprint(f"HTML report: {output_dir / 'cpplyzer-report.html'}")
    eprint(f"JSON report: {output_dir / 'cpplyzer-report.json'}")
    eprint(f"Findings: {report['summary']['total']}")
    return 0


def combine_issue_summary(issues: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return summarize_issues(issues)


def rel_link(from_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target, from_dir)).as_posix()


def render_dashboard(dashboard: Dict[str, Any]) -> str:
    metadata = dashboard["metadata"]
    summary = dashboard["summary"]
    projects = dashboard["projects"]
    issues = dashboard["issues"]
    generated_display = html.escape(format_generated_at_tr_eu(str(metadata.get("generatedAt", ""))))

    project_rows = []
    for project in projects:
        status = html.escape(project["status"])
        report_link = ""
        if project.get("reportHtml"):
            report_link = f'<a href="{html.escape(project["reportHtml"])}">project report</a>'
        else:
            report_link = '<span class="muted">not available</span>'
        error = html.escape(project.get("error", ""))
        project_rows.append(
            "<tr>"
            f"<td><code>{html.escape(project['project'])}</code></td>"
            f"<td><span class=\"status {status}\">{status}</span></td>"
            f"<td>{project.get('findings', 0)}</td>"
            f"<td>{report_link}</td>"
            f"<td class=\"error-cell\">{error}</td>"
            "</tr>"
        )

    issue_rows = []
    for issue in issues:
        severity = html.escape(str(issue.get("severity", "unknown")))
        analyzer = html.escape(str(issue.get("analyzer", "unknown")))
        rule = html.escape(str(issue.get("rule", "")))
        project = html.escape(str(issue.get("project", "")))
        file_name = html.escape(str(issue.get("file", "")))
        line = html.escape(str(issue.get("line", "")))
        column = html.escape(str(issue.get("column", "")))
        message = html.escape(str(issue.get("message", "")))
        snippet = render_snippet(issue.get("snippet", []))
        issue_rows.append(
            f"""
            <article class="issue">
              <header>
                <span class="badge {severity}">{severity}</span>
                <strong>{project}</strong>
                <span>{analyzer}</span>
                <code>{rule}</code>
              </header>
              <p>{message}</p>
              <div class="location"><code>{file_name}:{line}:{column}</code></div>
              <details>
                <summary>Source snippet</summary>
                <pre>{snippet}</pre>
              </details>
            </article>
            """
        )

    if not issue_rows:
        issue_rows.append('<p class="empty">No findings were reported by the enabled analyzers.</p>')

    severity_items = "".join(
        f"<li><strong>{html.escape(str(name))}</strong>: {count}</li>"
        for name, count in sorted(summary["bySeverity"].items())
    )
    analyzer_items = "".join(
        f"<li><strong>{html.escape(str(name))}</strong>: {count}</li>"
        for name, count in sorted(summary["byAnalyzer"].items())
    )
    warning_items = "".join(
        f"<li>{html.escape(str(item))}</li>"
        for item in dashboard.get("warnings", [])
    ) or "<li>No warnings.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Cpplyzer Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #1c2027;
      --muted: #667085;
      --line: #d7dce2;
      --accent: #2457a6;
      --error: #b42318;
      --warning: #b54708;
      --style: #175cd3;
      --info: #345c46;
      --ok: #027a48;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    h1, h2 {{ margin: 0 0 12px; letter-spacing: 0; }}
    h1 {{ font-size: 32px; }}
    h2 {{ font-size: 20px; margin-top: 28px; }}
    a {{ color: var(--accent); }}
    .meta, .muted {{ color: var(--muted); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin: 24px 0;
    }}
    .panel, .issue {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .count {{
      display: block;
      font-size: 34px;
      font-weight: 700;
      color: var(--accent);
    }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #eef2f6; }}
    .error-cell {{
      max-width: 520px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: var(--error);
    }}
    .status {{
      display: inline-block;
      border-radius: 4px;
      padding: 2px 7px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .success {{ background: var(--ok); }}
    .failed {{ background: var(--error); }}
    .issue {{ margin: 12px 0; }}
    .issue header {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
    }}
    .badge {{
      display: inline-block;
      border-radius: 4px;
      padding: 2px 7px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .error {{ background: var(--error); }}
    .warning {{ background: var(--warning); }}
    .style, .performance, .portability {{ background: var(--style); }}
    .information, .info, .unknown {{ background: var(--info); }}
    code, pre {{
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
    }}
    code {{ overflow-wrap: anywhere; }}
    .location {{
      color: var(--muted);
      margin-bottom: 10px;
    }}
    details {{
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 10px;
    }}
    summary {{ cursor: pointer; color: var(--accent); }}
    pre {{
      margin: 10px 0 0;
      padding: 12px;
      background: #101828;
      color: #f2f4f7;
      overflow-x: auto;
      border-radius: 6px;
    }}
    pre div {{ white-space: pre; }}
    .line-no {{
      display: inline-block;
      width: 54px;
      color: #98a2b3;
      user-select: none;
    }}
    .target {{ background: rgba(255, 196, 0, 0.18); }}
    .empty {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Cpplyzer Dashboard</h1>
    <p class="meta">Root: <code>{html.escape(metadata["root"])}</code><br>Generated: {generated_display}</p>

    <section class="summary">
      <div class="panel">
        <span class="count">{summary["totalFindings"]}</span>
        Total findings
      </div>
      <div class="panel">
        <span class="count">{summary["successfulProjects"]}/{summary["totalProjects"]}</span>
        Successful projects
      </div>
      <div class="panel">
        <strong>By severity</strong>
        <ul>{severity_items or "<li>No findings.</li>"}</ul>
      </div>
      <div class="panel">
        <strong>By analyzer</strong>
        <ul>{analyzer_items or "<li>No findings.</li>"}</ul>
      </div>
    </section>

    <h2>Projects</h2>
    <table>
      <thead><tr><th>Project</th><th>Status</th><th>Findings</th><th>Report</th><th>Error</th></tr></thead>
      <tbody>{''.join(project_rows)}</tbody>
    </table>

    <h2>Findings</h2>
    {''.join(issue_rows)}

    <h2>Warnings</h2>
    <div class="panel"><ul>{warning_items}</ul></div>
  </main>
</body>
</html>
"""


def generate_dashboard(
    root: Path,
    output_dir: Path,
    project_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    all_issues: List[Dict[str, Any]] = []
    warnings: List[str] = []
    projects: List[Dict[str, Any]] = []

    for item in project_results:
        project_path = Path(item["project"]).resolve()
        project_name = relative_display_path(project_path, root)
        if item["status"] == "success":
            report = item["report"]
            project_issues = deepcopy(report.get("issues", []))
            for issue in project_issues:
                issue["project"] = project_name
            all_issues.extend(project_issues)
            for warning in report.get("warnings", []):
                warnings.append(f"{project_name}: {warning}")
            report_html = Path(item["outputDir"]) / "cpplyzer-report.html"
            projects.append(
                {
                    "project": project_name,
                    "status": "success",
                    "findings": report["summary"]["total"],
                    "reportHtml": rel_link(output_dir, report_html),
                    "error": "",
                }
            )
        else:
            projects.append(
                {
                    "project": project_name,
                    "status": "failed",
                    "findings": 0,
                    "reportHtml": "",
                    "error": item.get("error", ""),
                }
            )
            warnings.append(f"{project_name}: {item.get('error', '')}")

    issue_summary = combine_issue_summary(all_issues)
    dashboard = {
        "metadata": {
            "tool": "Cpplyzer",
            "version": VERSION,
            "generatedAt": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
            "root": str(root),
        },
        "summary": {
            "totalProjects": len(projects),
            "successfulProjects": sum(1 for project in projects if project["status"] == "success"),
            "failedProjects": sum(1 for project in projects if project["status"] != "success"),
            "totalFindings": issue_summary["total"],
            "byAnalyzer": issue_summary["byAnalyzer"],
            "bySeverity": issue_summary["bySeverity"],
        },
        "projects": projects,
        "warnings": warnings,
        "issues": sorted(all_issues, key=issue_sort_key),
    }
    write_json(output_dir / "cpplyzer-dashboard.json", dashboard)
    (output_dir / "index.html").write_text(render_dashboard(dashboard), encoding="utf-8", newline="\n")
    return dashboard


def analyze_many(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve() if args.config else None
    cfg, config_dir = load_config(config_path)
    apply_cli_overrides(cfg, args)

    root = Path(args.root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Root directory not found: {root}")

    output_dir = Path(args.output).resolve()
    build_root = Path(args.build_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_root.mkdir(parents=True, exist_ok=True)

    projects = discover_pro_files(root, cfg)
    if not projects:
        raise RuntimeError(f"No .pro files were discovered under: {root}")

    eprint(f"Discovered {len(projects)} .pro project(s).")
    project_results: List[Dict[str, Any]] = []
    for project_file in projects:
        slug = project_slug(project_file, root)
        project_output = output_dir / "projects" / slug
        project_build = build_root / slug
        eprint(f"Analyzing {relative_display_path(project_file, root)}...")
        try:
            report = run_analysis_for_project(
                project_file,
                cfg,
                config_dir,
                project_output,
                project_build,
                compile_commands_override=args.compile_commands or "",
                build_log_override=args.build_log or "",
            )
            project_results.append(
                {
                    "project": str(project_file),
                    "status": "success",
                    "outputDir": str(project_output),
                    "report": report,
                }
            )
        except Exception as exc:
            project_results.append(
                {
                    "project": str(project_file),
                    "status": "failed",
                    "outputDir": str(project_output),
                    "error": str(exc),
                }
            )
            eprint(f"Project failed: {project_file}: {exc}")

    dashboard = generate_dashboard(root, output_dir, project_results)
    eprint(f"Dashboard: {output_dir / 'index.html'}")
    eprint(f"Dashboard JSON: {output_dir / 'cpplyzer-dashboard.json'}")
    eprint(f"Projects: {dashboard['summary']['successfulProjects']}/{dashboard['summary']['totalProjects']} succeeded")
    eprint(f"Findings: {dashboard['summary']['totalFindings']}")

    if dashboard["summary"]["failedProjects"] and not args.allow_project_failures:
        return 2
    return 0


def init_config(args: argparse.Namespace) -> int:
    destination = Path(args.output).resolve()
    if destination.exists() and not args.force:
        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
    write_json(destination, DEFAULT_CONFIG)
    print(f"Wrote {destination}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpplyzer",
        description="Offline C++ static analysis orchestrator for Qt/qmake/MSVC projects.",
    )
    parser.add_argument("--version", action="version", version=f"Cpplyzer {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init-config", help="Write an editable JSON configuration file.")
    init.add_argument("-o", "--output", default="cpplyzer.json", help="Config file to create.")
    init.add_argument("--force", action="store_true", help="Overwrite the config file if it exists.")
    init.set_defaults(func=init_config)

    analyze_parser = subparsers.add_parser("analyze", help="Run static analysis and generate reports.")
    analyze_parser.add_argument("project", help="Path to the Qt .pro file.")
    analyze_parser.add_argument("--config", help="Path to cpplyzer JSON config.")
    analyze_parser.add_argument("--output", default="reports/cpplyzer", help="Report output directory.")
    analyze_parser.add_argument("--build-dir", default="build/cpplyzer-capture", help="Temporary qmake build directory.")
    analyze_parser.add_argument("--compile-commands", help="Use an existing compile_commands.json.")
    analyze_parser.add_argument("--build-log", help="Create compile_commands.json from an existing jom/MSVC build log.")
    analyze_parser.add_argument("--qmake", help="Override qmake path.")
    analyze_parser.add_argument("--jom", help="Override jom path.")
    analyze_parser.add_argument("--clang-tidy", help="Override clang-tidy path.")
    analyze_parser.add_argument("--cppcheck", help="Override cppcheck path.")
    analyze_parser.add_argument("--skip-clang-tidy", action="store_true", help="Disable clang-tidy for this run.")
    analyze_parser.add_argument("--skip-cppcheck", action="store_true", help="Disable cppcheck for this run.")
    analyze_parser.add_argument("--strict-tools", action="store_true", help="Fail if an enabled analyzer is missing.")
    analyze_parser.set_defaults(func=analyze)

    analyze_many_parser = subparsers.add_parser(
        "analyze-many",
        help="Discover .pro files under a root directory and generate one dashboard.",
    )
    analyze_many_parser.add_argument("root", help="Root directory to search for Qt .pro files.")
    analyze_many_parser.add_argument("--config", help="Path to cpplyzer JSON config.")
    analyze_many_parser.add_argument("--output", default="reports/cpplyzer", help="Dashboard output directory.")
    analyze_many_parser.add_argument("--build-dir", default="build/cpplyzer-capture", help="Temporary qmake build root.")
    analyze_many_parser.add_argument("--compile-commands", help="Use one existing compile_commands.json for discovered projects.")
    analyze_many_parser.add_argument("--build-log", help="Create compile_commands.json from one existing jom/MSVC build log.")
    analyze_many_parser.add_argument("--qmake", help="Override qmake path.")
    analyze_many_parser.add_argument("--jom", help="Override jom path.")
    analyze_many_parser.add_argument("--clang-tidy", help="Override clang-tidy path.")
    analyze_many_parser.add_argument("--cppcheck", help="Override cppcheck path.")
    analyze_many_parser.add_argument("--skip-clang-tidy", action="store_true", help="Disable clang-tidy for this run.")
    analyze_many_parser.add_argument("--skip-cppcheck", action="store_true", help="Disable cppcheck for this run.")
    analyze_many_parser.add_argument("--strict-tools", action="store_true", help="Fail if an enabled analyzer is missing.")
    analyze_many_parser.add_argument(
        "--allow-project-failures",
        action="store_true",
        help="Return exit code 0 even if one or more discovered projects fail to analyze.",
    )
    analyze_many_parser.set_defaults(func=analyze_many)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        eprint(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
