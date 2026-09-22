"""mcp-kubectl — real kubectl, over MCP.

Two tools, one binary: `read` for commands that only look, `run` for anything
kubectl can do. The split is not a permission boundary — both run as the same
ServiceAccount, and the API server and admission policies decide what is
allowed. It exists so that a caller (and a human watching an incident channel)
can tell a lookup from a change without inspecting arguments.

Why a whole kubectl instead of more typed tools: a typed tool has to be told
the apiVersion of every kind, and an agent that has to guess `postgresql.cnpg.io/v1`
burns a call per guess. kubectl already knows: it resolves kinds, short names
and aliases server-side, and `api-resources` lists them all.
"""
from __future__ import annotations

import json
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import runner, verbs
from .runner import MAX_TIMEOUT_S, RunError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kubectl-mcp")

mcp = FastMCP(
    "kubectl",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8080")),
    streamable_http_path="/mcp",
    # Stateless: a multiplexing MCP gateway (agentgateway) fans out tools/list on
    # a cached session id; FastMCP's default stateful mode drops idle sessions,
    # after which every fanout 404s and the gateway silently drops this upstream.
    # Stateless has no session to lose — each call is self-contained.
    stateless_http=True,
)


async def _call(args: list[str], timeout_s: int, stdin: str) -> str:
    try:
        result = await runner.run(args, timeout_s=timeout_s, stdin=stdin)
    except RunError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:                     # never hand back a traceback
        log.exception("kubectl failed")
        return json.dumps({"error": f"kubectl failed: {type(e).__name__}"})
    log.info("kubectl %s -> exit %s", " ".join(args), result["exit_code"])
    return json.dumps(result, default=str)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
async def read(args: list[str], timeout_s: int = 0) -> str:
    """Run a READ-ONLY kubectl command and return its output.

    args is kubectl's argument list, without "kubectl" itself, e.g.
    ["get","pods","-n","media","-o","wide"] or ["api-resources"] or
    ["describe","cluster","shared-pg","-n","databases"]. kubectl resolves kinds
    and short names itself, so no apiVersion is needed: `get cluster`,
    `get helmrelease`, `get pvc` all work. Use this for get, describe, logs,
    events, top, explain, api-resources, diff, version.

    There is no shell: no pipes, no redirection, no globbing. Narrow output
    with kubectl's own flags (-o jsonpath=..., --field-selector, -l, --tail).
    Streaming and interactive flags (-w, -f/--follow, exec -it, port-forward)
    never return and will hit the timeout.

    Anything that is not a read is refused here — use run() for that.
    """
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return json.dumps({"error": "args must be a list of strings"})
    if not verbs.is_read(args):
        cmd = verbs.command_of(args)[0] or "(none)"
        return json.dumps({"error": f"'{cmd}' is not a read-only kubectl command; "
                                    f"call run() instead"})
    return await _call(args, timeout_s, "")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
async def run(args: list[str], timeout_s: int = 0, stdin: str = "") -> str:
    """Run ANY kubectl command, including ones that change the cluster.

    args is kubectl's argument list without "kubectl", e.g.
    ["rollout","restart","deploy/jellyfin","-n","media"],
    ["delete","pod","x","-n","ai"], ["apply","-f","-"] with the manifest in
    stdin, ["patch","hr","jellyfin","-n","media","--type=merge","-p","{...}"].

    stdin is fed to the command (use it with `-f -`). timeout_s defaults to 60
    and is capped; the command is killed when it expires.

    There is no shell and no argument filtering here: what you may do is
    decided by the ServiceAccount this server runs as, plus the cluster's
    admission policies. A refusal from the API server comes back verbatim in
    stderr — read it, do not try another route to the same change.

    Use read() for lookups: it is announced as a lookup rather than an action.
    """
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return json.dumps({"error": "args must be a list of strings"})
    return await _call(args, timeout_s, stdin)


def main() -> None:
    log.info("kubectl MCP server on %s:%s/mcp (max timeout %ss)",
             mcp.settings.host, mcp.settings.port, MAX_TIMEOUT_S)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
