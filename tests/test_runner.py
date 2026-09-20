import asyncio
import os

import pytest

from kubectlmcp import runner


def call(args, **kw):
    return asyncio.run(runner.run(args, **kw))


@pytest.fixture(autouse=True)
def fake_kubectl(tmp_path, monkeypatch):
    """A stand-in for kubectl, so the tests never need a cluster."""
    p = tmp_path / "kubectl"
    p.write_text("#!/bin/sh\n"
                 'case "$1" in\n'
                 '  sleep) sleep 30 ;;\n'
                 '  big) head -c 1000000 /dev/zero | tr "\\0" "x" ;;\n'
                 '  cat) cat ;;\n'
                 '  fail) echo "Error from server (Forbidden): nope" >&2; exit 1 ;;\n'
                 '  *) echo "args: $*" ;;\n'
                 'esac\n')
    p.chmod(0o755)
    monkeypatch.setattr(runner, "KUBECTL_BIN", str(p))
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])


def test_arguments_are_passed_through_verbatim():
    r = call(["get", "pods", "-l", "app=x;rm -rf /"])
    assert r["exit_code"] == 0
    assert "app=x;rm -rf /" in r["stdout"]          # one argv element, never a shell token


def test_a_refusal_comes_back_whole():
    r = call(["fail"])
    assert r["exit_code"] == 1 and "Forbidden" in r["stderr"]


def test_a_hanging_command_is_killed_not_left_running():
    with pytest.raises(runner.RunError) as e:
        call(["sleep"], timeout_s=1)
    assert "limit" in str(e.value)


def test_timeout_is_clamped():
    assert runner.clamp_timeout(10 ** 6) == runner.MAX_TIMEOUT_S
    assert runner.clamp_timeout(0) == runner.DEFAULT_TIMEOUT_S


def test_output_is_capped_and_says_so():
    r = call(["big"])
    assert r["truncated"] and len(r["stdout"]) < 1000000 and "truncated" in r["stdout"]


def test_stdin_reaches_the_command():
    r = call(["cat"], stdin="apiVersion: v1\n")
    assert "apiVersion: v1" in r["stdout"]


def test_empty_args_are_refused():
    with pytest.raises(runner.RunError):
        call([])
