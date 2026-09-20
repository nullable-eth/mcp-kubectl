# mcp-kubectl

Real `kubectl`, exposed over the Model Context Protocol on streamable HTTP at
`/mcp`. Built for an autonomous cluster agent that was spending calls guessing
API groups for typed tools.

## Tools

| tool | does |
|---|---|
| `read` | a read-only kubectl command (`get`, `describe`, `logs`, `events`, `top`, `explain`, `api-resources`, `diff`, `version`, …) |
| `run`  | any kubectl command, including ones that change the cluster; takes `stdin` for `-f -` |

Both take `args`, kubectl's argument list without `kubectl` itself
(`["get","pods","-n","media","-o","wide"]`), and an optional `timeout_s`.
They return JSON: `command`, `exit_code`, `stdout`, `stderr`, `truncated`.

## Why a whole kubectl

Typed Kubernetes MCP tools ask for an `apiVersion` for every kind, and an agent
that has to remember whether a CNPG cluster is `postgresql.cnpg.io/v1` or
`db.cnpg.io/v1` will eventually spend a tool call finding out. kubectl already
knows: it resolves kinds, short names and aliases against the API server's own
discovery, and `api-resources` lists every kind with its group.

## What decides what it may do

**The ServiceAccount it runs as.** Kubernetes RBAC and admission control are
the boundary; this server adds no allowlist of its own, because a second,
weaker copy of that boundary would only fail differently — and would be the
thing that stops an operator's agent mid-incident. Run it with exactly the
permissions the caller should have, and a refusal comes back verbatim in
`stderr`.

The `read` / `run` split is **not** a boundary: both run as the same account.
`read` refuses anything not on a conservative read-only list so a caller can
label a lookup as a lookup, and it carries `readOnlyHint` in its MCP
annotations so a client can present it that way.

What the server does enforce, since none of it depends on the command:

- **No shell.** The command is an argv, never a string a shell sees, so no
  pipes, redirection, globbing or injection through an argument value.
- **A timeout.** Default 60s, capped by `MAX_TIMEOUT_S` (600). The process
  group is killed on expiry, so `logs -f`, `exec -it` and `port-forward`
  cannot pin a worker.
- **Bounded output.** 256 KiB by default, then a note telling the caller to
  narrow it with `-o jsonpath`, `--field-selector`, `-l` or `--tail`.
- **Bounded concurrency.** `MAX_CONCURRENT` (4) commands at a time.

Secrets are not treated specially here: `kubectl get secret -o yaml` prints
what RBAC allows. Give the ServiceAccount no access to Secrets, put a
redacting proxy in front, or both.

## Settings

| variable | default | meaning |
|---|---|---|
| `PORT` / `HOST` | `8080` / `0.0.0.0` | listen address |
| `KUBECTL_BIN` | `kubectl` | binary to run |
| `DEFAULT_TIMEOUT_S` | `60` | per-command timeout when the caller gives none |
| `MAX_TIMEOUT_S` | `600` | ceiling for `timeout_s` |
| `MAX_OUTPUT_BYTES` | `262144` | cap on captured stdout/stderr |
| `MAX_CONCURRENT` | `4` | commands in flight |

In a pod, kubectl uses the mounted ServiceAccount token automatically; mount
one (`automountServiceAccountToken: true`) and set no kubeconfig.

## Run

```
pip install -r requirements.txt
python -m kubectlmcp.server
python -m pytest -q tests          # no cluster needed: kubectl is stubbed
```

Push to `main` → `:latest` + `:sha-…` on ghcr.io. Pin by `sha-`.
