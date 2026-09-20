from kubectlmcp import verbs


def test_command_ignores_flags_and_their_values():
    assert verbs.command_of(["-n", "media", "get", "pods"]) == ("get", "pods")
    assert verbs.command_of(["--namespace=ai", "describe", "pod", "x"]) == ("describe", "pod")
    assert verbs.command_of(["-A", "get", "hr"]) == ("get", "hr")
    assert verbs.command_of([]) == ("", "")


def test_reads_are_reads():
    for args in (["get", "pods", "-A"], ["api-resources"], ["logs", "x", "--tail", "5"],
                 ["describe", "cluster", "shared-pg", "-n", "databases"],
                 ["-n", "media", "top", "pod"], ["explain", "hr"], ["diff", "-f", "-"]):
        assert verbs.is_read(args), args


def test_changes_are_not_reads():
    for args in (["delete", "pod", "x"], ["apply", "-f", "-"], ["rollout", "restart", "deploy/x"],
                 ["patch", "hr", "x", "--type=merge", "-p", "{}"], ["exec", "x", "--", "sh"],
                 ["config", "set-context", "y"], ["auth", "reconcile", "-f", "-"],
                 ["scale", "deploy/x", "--replicas=0"], []):
        assert not verbs.is_read(args), args


def test_a_flag_value_cannot_masquerade_as_the_command():
    # -o delete would otherwise read as the command "delete"
    assert verbs.command_of(["get", "-o", "yaml", "pods"]) == ("get", "pods")
    assert verbs.is_read(["get", "-o", "yaml", "pods"])
