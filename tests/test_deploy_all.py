"""Tests for deploy_all's pre-deploy cleanup gating.

The bug: orphaned-log-group deletion ran UNCONDITIONALLY, so a healthy
(CREATE_COMPLETE/UPDATE_COMPLETE) stack would have its managed log groups
deleted — breaking the in-place CloudFormation UPDATE. The fix gates the
log-group deletion on the SAME failed/absent condition as the stack deletion.

deploy_all.py used to run its whole deploy flow at import; it must now live
under main() + an ``if __name__ == '__main__'`` guard so it can be imported
here without doing anything.
"""

import importlib

import pytest


@pytest.fixture
def deploy_all():
    """Import deploy_all fresh (it must be import-safe — no deploy at import)."""
    mod = importlib.import_module("deploy_all")
    return importlib.reload(mod)


# --- _should_cleanup: pure state gate -------------------------------------

@pytest.mark.parametrize(
    "status",
    ["ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED", None],
)
def test_should_cleanup_true_for_failed_or_absent(deploy_all, status):
    assert deploy_all._should_cleanup(status) is True


@pytest.mark.parametrize("status", ["CREATE_COMPLETE", "UPDATE_COMPLETE"])
def test_should_cleanup_false_for_healthy(deploy_all, status):
    assert deploy_all._should_cleanup(status) is False


# --- pre_deploy_cleanup: healthy stack is left completely alone ------------

def test_healthy_stack_issues_no_deletes(deploy_all, monkeypatch):
    calls = []

    def fake_aws_cli(*args):
        calls.append(args)
        if args[:2] == ("cloudformation", "describe-stacks"):
            return "UPDATE_COMPLETE"
        return ""

    monkeypatch.setattr(deploy_all, "aws_cli", fake_aws_cli)

    deploy_all.pre_deploy_cleanup("us-east-1")

    verbs = [args for args in calls]
    assert not any(a[:2] == ("cloudformation", "delete-stack") for a in verbs)
    assert not any(a[:2] == ("logs", "delete-log-group") for a in verbs)
    # It still queried status (and may have listed groups), but deleted nothing.
    assert any(a[:2] == ("cloudformation", "describe-stacks") for a in verbs)


# --- pre_deploy_cleanup: failed stack is cleaned up, groups included -------

def test_failed_stack_deletes_stack_and_orphan_log_groups(deploy_all, monkeypatch):
    calls = []
    prefix = deploy_all.LOG_GROUP_PREFIX

    def fake_aws_cli(*args):
        calls.append(args)
        if args[:2] == ("cloudformation", "describe-stacks"):
            return "ROLLBACK_COMPLETE"
        if args[:2] == ("logs", "describe-log-groups"):
            return f"{prefix}abc {prefix}def"
        return ""

    monkeypatch.setattr(deploy_all, "aws_cli", fake_aws_cli)
    # delete-stack path also calls subprocess.run for the waiter.
    monkeypatch.setattr(deploy_all.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(deploy_all, "resolve_exe", lambda name: name)

    deploy_all.pre_deploy_cleanup("us-east-1")

    assert any(a[:2] == ("cloudformation", "delete-stack") for a in calls)
    deleted = [a[-1] for a in calls if a[:2] == ("logs", "delete-log-group")]
    # Both orphaned groups were removed.
    assert f"{prefix}abc" in " ".join(str(x) for a in calls for x in a)
    assert sum(1 for a in calls if a[:2] == ("logs", "delete-log-group")) == 2
