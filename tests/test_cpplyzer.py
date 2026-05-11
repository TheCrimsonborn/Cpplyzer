import pytest
from unittest.mock import patch
from cpplyzer import command_failure_message, CommandResult

def test_command_failure_message_no_label_no_logs():
    result = CommandResult(
        tool="qmake",
        command=["qmake", "test.pro"],
        cwd="/tmp/build",
        exit_code=1,
        duration_seconds=0.5,
        stdout_path="/tmp/build/qmake.stdout.log",
        stderr_path="/tmp/build/qmake.stderr.log",
    )

    with patch("cpplyzer.log_excerpt", return_value=""):
        msg = command_failure_message(result)

        expected_lines = [
            "qmake failed with exit code 1.",
            "cwd: /tmp/build",
            "command: qmake test.pro",
            "stdout log: /tmp/build/qmake.stdout.log",
            "stderr log: /tmp/build/qmake.stderr.log"
        ]
        assert msg == "\n".join(expected_lines)


def test_command_failure_message_with_label_and_logs():
    result = CommandResult(
        tool="qmake",
        command=["qmake", "test.pro"],
        cwd="/tmp/build",
        exit_code=2,
        duration_seconds=1.0,
        stdout_path="/tmp/build/qmake.stdout.log",
        stderr_path="/tmp/build/qmake.stderr.log",
    )

    def mock_log_excerpt(path):
        if path.endswith("stdout.log"):
            return "stdout line 1\nstdout line 2"
        elif path.endswith("stderr.log"):
            return "stderr error!"
        return ""

    with patch("cpplyzer.log_excerpt", side_effect=mock_log_excerpt):
        msg = command_failure_message(result, label="QMake Step")

        expected_lines = [
            "QMake Step failed with exit code 2.",
            "cwd: /tmp/build",
            "command: qmake test.pro",
            "stderr:",
            "stderr error!",
            "stdout:",
            "stdout line 1\nstdout line 2",
            "stdout log: /tmp/build/qmake.stdout.log",
            "stderr log: /tmp/build/qmake.stderr.log"
        ]
        assert msg == "\n".join(expected_lines)


def test_command_failure_message_only_stdout():
    result = CommandResult(
        tool="jom",
        command=["jom", "-n"],
        cwd="/tmp/build",
        exit_code=3,
        duration_seconds=1.5,
        stdout_path="/tmp/build/jom.stdout.log",
        stderr_path="/tmp/build/jom.stderr.log",
    )

    def mock_log_excerpt(path):
        if path.endswith("stdout.log"):
            return "only stdout"
        return ""

    with patch("cpplyzer.log_excerpt", side_effect=mock_log_excerpt):
        msg = command_failure_message(result)

        expected_lines = [
            "jom failed with exit code 3.",
            "cwd: /tmp/build",
            "command: jom -n",
            "stdout:",
            "only stdout",
            "stdout log: /tmp/build/jom.stdout.log",
            "stderr log: /tmp/build/jom.stderr.log"
        ]
        assert msg == "\n".join(expected_lines)


def test_command_failure_message_only_stderr():
    result = CommandResult(
        tool="cl",
        command=["cl.exe", "/c", "main.cpp"],
        cwd="/tmp/build",
        exit_code=4,
        duration_seconds=2.0,
        stdout_path="/tmp/build/cl.stdout.log",
        stderr_path="/tmp/build/cl.stderr.log",
    )

    def mock_log_excerpt(path):
        if path.endswith("stderr.log"):
            return "only stderr"
        return ""

    with patch("cpplyzer.log_excerpt", side_effect=mock_log_excerpt):
        msg = command_failure_message(result)

        expected_lines = [
            "cl failed with exit code 4.",
            "cwd: /tmp/build",
            "command: cl.exe /c main.cpp",
            "stderr:",
            "only stderr",
            "stdout log: /tmp/build/cl.stdout.log",
            "stderr log: /tmp/build/cl.stderr.log"
        ]
        assert msg == "\n".join(expected_lines)
