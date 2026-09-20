"""Which kubectl commands only read.

This is NOT a permission boundary — the ServiceAccount is. It exists so a
caller can say "this one only looks", and so a UI that announces actions can
tell a `get` apart from a `delete` without asking the API server.

read() therefore has to be conservative: anything not known to be read-only is
treated as a change.
"""
from __future__ import annotations

READ_ONLY = frozenset({
    "get", "describe", "explain", "api-resources", "api-versions", "cluster-info",
    "config", "diff", "events", "logs", "top", "version", "auth", "kustomize",
})

# Subcommands of an otherwise read-only command that are NOT reads.
NOT_READ_ONLY = {
    ("config", "set"), ("config", "set-context"), ("config", "set-cluster"),
    ("config", "set-credentials"), ("config", "unset"), ("config", "use-context"),
    ("config", "delete-context"), ("config", "delete-cluster"), ("config", "rename-context"),
    ("auth", "reconcile"),
}


def command_of(args: list[str]) -> tuple[str, str]:
    """The kubectl command and subcommand in args, ignoring flags and values.

    Only the first two non-flag words matter, and a value after a flag that
    takes one (-n mynamespace) must not be mistaken for the command.
    """
    words: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            break
        if a.startswith("-"):
            # "-n x" / "--namespace x" take a value; "--all-namespaces" and
            # "-n=x" / "--namespace=x" do not.
            skip = "=" not in a and a not in _VALUELESS
            continue
        words.append(a)
        if len(words) == 2:
            break
    return (words[0] if words else "", words[1] if len(words) > 1 else "")


# Flags that never take a value, so the next word is still the command.
_VALUELESS = frozenset({
    "-A", "--all-namespaces", "-w", "--watch", "-f", "--follow", "--recursive",
    "-R", "--prune", "--force", "--wait", "--dry-run", "-it", "-i", "-t",
    "--previous", "-p", "--all", "--ignore-not-found", "--show-labels",
})


def is_read(args: list[str]) -> bool:
    cmd, sub = command_of(args)
    if cmd not in READ_ONLY:
        return False
    if (cmd, sub) in NOT_READ_ONLY:
        return False
    # `kubectl get -f -` and friends still only read; `apply -f -` is not in
    # READ_ONLY at all, so nothing here can reach a write.
    return True
