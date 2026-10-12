"""Outer runs report their tree status correctly.

An outer run that never ran itself (no run_state.yml, own status = "created")
is a pure container. Its "created" status must NOT pollute the tree_status
rollup: if all 16 children succeeded, tree_status should be "succeeded", not
"created".

An outer that DID run (has a run state: SDK parent, vmn-exp run orchestrator)
still participates in the rollup: a failed orchestrator fails its tree.
"""
import pytest

from vmn_exp.core.tree import annotate_tree, annotate_rows, rollup_status
from vmn_exp.core.status import CREATED, FAILED, RUNNING, STUCK, SUCCEEDED


def _row(verstr, parent=None, status="created", **extra):
    """A minimal row with the fields annotate_tree reads."""
    r = {"verstr": verstr, "status": status, **extra}
    if parent:
        r["parent"] = parent
    return r


def _run_state(exit_code=None, state="running", heartbeat=None):
    """A run_state dict as annotate_rows expects."""
    rs = {"state": state}
    if exit_code is not None:
        rs["exit_code"] = exit_code
    if heartbeat:
        rs["heartbeat"] = heartbeat
    return rs


class TestContainerOuterTreeStatus:
    """An outer with no run state (own status 'created') is a container:
    its own 'created' must be excluded from the tree_status rollup."""

    def test_all_children_succeeded(self):
        """16 succeeded children under a container outer -> tree_status 'succeeded'."""
        outer = _row("outer.1")
        children = [_row(f"inner.{i}", parent="outer.1", status="succeeded")
                     for i in range(16)]
        rows = annotate_tree([outer] + children)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["tree_status"] == SUCCEEDED

    def test_one_failed_child(self):
        """15 succeeded + 1 failed under a container outer -> tree_status 'failed'."""
        outer = _row("outer.1")
        children = [_row(f"inner.{i}", parent="outer.1", status="succeeded")
                     for i in range(15)]
        children.append(_row("inner.15", parent="outer.1", status="failed"))
        rows = annotate_tree([outer] + children)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["tree_status"] == FAILED

    def test_one_running_child(self):
        """15 succeeded + 1 running under a container outer -> tree_status 'running'."""
        outer = _row("outer.1")
        children = [_row(f"inner.{i}", parent="outer.1", status="succeeded")
                     for i in range(15)]
        children.append(_row("inner.15", parent="outer.1", status="running"))
        rows = annotate_tree([outer] + children)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["tree_status"] == RUNNING

    def test_no_children_stays_created(self):
        """A single run (no children) with status 'created' stays 'created'."""
        rows = annotate_tree([_row("single.1")])
        assert rows[0]["tree_status"] == CREATED
        assert rows[0]["kind"] == "single"


class TestOrchestratorOuterTreeStatus:
    """An outer that DID run (has run_state) still participates in the rollup."""

    def test_failed_orchestrator_fails_tree(self):
        """Outer ran and failed + succeeded children -> tree_status 'failed'."""
        outer = _row("outer.1", status="failed")
        children = [_row(f"inner.{i}", parent="outer.1", status="succeeded")
                     for i in range(4)]
        rows = annotate_tree([outer] + children)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["tree_status"] == FAILED

    def test_succeeded_orchestrator_with_succeeded_children(self):
        """Outer ran and succeeded + succeeded children -> tree_status 'succeeded'."""
        outer = _row("outer.1", status="succeeded")
        children = [_row(f"inner.{i}", parent="outer.1", status="succeeded")
                     for i in range(4)]
        rows = annotate_tree([outer] + children)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["tree_status"] == SUCCEEDED


class TestNestedContainerOuters:
    """Inner-outer without run state under outer without run state."""

    def test_nested_containers(self):
        """Two levels of containers: both should get tree_status from leaves only."""
        top = _row("top.1")
        mid = _row("mid.1", parent="top.1")
        leaves = [_row(f"leaf.{i}", parent="mid.1", status="succeeded")
                  for i in range(4)]
        rows = annotate_tree([top, mid] + leaves)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["mid.1"]["tree_status"] == SUCCEEDED
        assert by_v["top.1"]["tree_status"] == SUCCEEDED

    def test_nested_containers_with_failure(self):
        """Nested containers with one failed leaf -> both show 'failed'."""
        top = _row("top.1")
        mid = _row("mid.1", parent="top.1")
        leaves = [_row(f"leaf.{i}", parent="mid.1", status="succeeded")
                  for i in range(3)]
        leaves.append(_row("leaf.3", parent="mid.1", status="failed"))
        rows = annotate_tree([top, mid] + leaves)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["mid.1"]["tree_status"] == FAILED
        assert by_v["top.1"]["tree_status"] == FAILED


class TestAnnotateRowsContainerOuter:
    """The annotate_rows path (status derived from run_states) should also
    exclude a container outer's 'created' from the rollup."""

    def test_no_run_state_all_succeeded(self):
        """annotate_rows: outer with no run state + succeeded children."""
        outer = {"verstr": "outer.1", "timestamp": "2026-01-01T00:00:00Z"}
        children = [
            {"verstr": f"inner.{i}", "parent": "outer.1",
             "timestamp": "2026-01-01T00:00:00Z"}
            for i in range(4)
        ]
        run_states = {}
        for i in range(4):
            run_states[f"inner.{i}"] = _run_state(exit_code=0, state="finished")
        # outer has NO run_state entry
        rows = annotate_rows([outer] + children, run_states)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["status"] == CREATED
        assert by_v["outer.1"]["tree_status"] == SUCCEEDED

    def test_with_run_state_failed(self):
        """annotate_rows: outer with failed run state + succeeded children."""
        outer = {"verstr": "outer.1", "timestamp": "2026-01-01T00:00:00Z"}
        children = [
            {"verstr": f"inner.{i}", "parent": "outer.1",
             "timestamp": "2026-01-01T00:00:00Z"}
            for i in range(4)
        ]
        run_states = {
            "outer.1": _run_state(exit_code=1, state="finished"),
        }
        for i in range(4):
            run_states[f"inner.{i}"] = _run_state(exit_code=0, state="finished")
        rows = annotate_rows([outer] + children, run_states)
        by_v = {r["verstr"]: r for r in rows}
        assert by_v["outer.1"]["status"] == FAILED
        assert by_v["outer.1"]["tree_status"] == FAILED
