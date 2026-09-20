"""Run kubectl as a fixed argv — never a shell string — with a hard timeout and
a bounded amount of captured output.

There is no argument allowlist. The boundary is the ServiceAccount this pod
runs as: the API server decides what the caller may read and change, and
admission policies decide the rest. A filter here would only add a second,
weaker copy of that boundary, and would be the thing that stops an operator's
agent from doing its job at 3am.

What IS enforced, because it does not depend on what the command is: no shell,
a timeout (an interactive or hanging command cannot pin a worker forever), a
cap on captured output, and a limit on how many run at once.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import signal

DEFAULT_TIMEOUT_S = int(os.environ.get("DEFAULT_TIMEOUT_S", "60"))
MAX_TIMEOUT_S = int(os.environ.get("MAX_TIMEOUT_S", "600"))
MAX_OUTPUT_BYTES = int(os.environ.get("MAX_OUTPUT_BYTES", str(256 * 1024)))
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "4"))
KUBECTL_BIN = os.environ.get("KUBECTL_BIN", "kubectl")

_SEM = asyncio.Semaphore(MAX_CONCURRENT)


class RunError(RuntimeError):
    """The command could not be run or did not finish. Safe to return."""


def kubectl_path() -> str:
    p = shutil.which(KUBECTL_BIN) or (KUBECTL_BIN if os.path.isabs(KUBECTL_BIN) else "")
    if not p:
        raise RunError(f"kubectl not found on PATH ({KUBECTL_BIN})")
    return p


def clamp_timeout(timeout_s: int | None) -> int:
    t = DEFAULT_TIMEOUT_S if not timeout_s or timeout_s <= 0 else int(timeout_s)
    return min(t, MAX_TIMEOUT_S)


async def run(args: list[str], *, timeout_s: int | None = None,
              stdin: str = "") -> dict:
    """kubectl <args>. Returns {command, exit_code, stdout, stderr, truncated}."""
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise RunError("args must be a list of strings")
    if not args:
        raise RunError("no arguments: pass kubectl's arguments, e.g. ['get','pods','-A']")
    timeout = clamp_timeout(timeout_s)
    argv = [kubectl_path(), *args]
    async with _SEM:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,      # own process group, so children die too
            )
        except OSError as e:
            raise RunError(f"could not start kubectl: {e}")
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(input=stdin.encode() if stdin else None),
                timeout=timeout)
        except asyncio.TimeoutError:
            _kill(proc)
            await proc.wait()
            raise RunError(
                f"kubectl exceeded its {timeout}s limit and was killed. Commands that "
                f"wait for input or follow a stream (exec -it, logs -f, port-forward) "
                f"never return; drop -f/-it, or raise timeout_s (max {MAX_TIMEOUT_S}).")
    stdout, cut_out = _cap(out)
    stderr, cut_err = _cap(err)
    return {"command": "kubectl " + " ".join(args),
            "exit_code": proc.returncode if proc.returncode is not None else -1,
            "stdout": stdout, "stderr": stderr,
            "truncated": cut_out or cut_err}


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def _cap(b: bytes) -> tuple[str, bool]:
    if len(b) > MAX_OUTPUT_BYTES:
        return (b[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
                + "\n...[truncated: narrow the output with -o jsonpath, --field-selector, "
                  "--tail or a label selector]"), True
    return b.decode("utf-8", "replace"), False
