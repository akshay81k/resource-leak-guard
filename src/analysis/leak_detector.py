"""Detect resource leaks using forward dataflow analysis on the CFG.

Combines:
1. Forward dataflow propagation of OPEN/CLOSED states along CFG edges
2. Pattern-based exception-path leak detection
3. Confidence scoring (DEFINITE vs POSSIBLE)
"""

from __future__ import annotations

from collections import defaultdict
from tree_sitter import Node

from src.models import CFG, Finding, ResourceHandle, ResourceState, Confidence
from src.rules.schema import LanguageRules
from src.analysis.resource_tracker import (
    track_resources,
    _find_nodes_by_type,
    _find_close_calls,
)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def detect_leaks(
    file_path: str,
    method_name: str,
    cfg: CFG,
    rules: LanguageRules,
    source_bytes: bytes,
) -> list[Finding]:
    """Run leak detection on a single method's CFG.

    Returns a list of ``Finding`` objects for resources that leak.
    """
    handles = track_resources(cfg, rules, source_bytes)
    if not handles:
        return []

    # Forward dataflow
    exit_states = _forward_dataflow(cfg, handles, rules)

    # Classify resources at exit blocks
    leaked: set[int] = set()      # OPEN at any exit
    closed: set[int] = set()      # CLOSED at some exit

    for exit_id in cfg.exit_ids:
        state = exit_states.get(exit_id, {})
        for rid in range(len(handles)):
            rs = state.get(rid)
            if rs == ResourceState.OPEN:
                leaked.add(rid)
            elif rs == ResourceState.CLOSED:
                closed.add(rid)

    # Resources closed on ALL exit paths (never OPEN at any exit)
    fully_closed = closed - leaked

    # Exception-path check for resources that appear fully closed
    exception_leaked: set[int] = set()
    for rid in fully_closed:
        h = handles[rid]
        if not h.is_safe_wrapped and not _is_exception_safe(h, cfg, rules):
            exception_leaked.add(rid)

    all_leaked = leaked | exception_leaked

    # Confidence adjustments
    arg_passed = _find_argument_passing(cfg, handles, rules)
    reassigned = _find_reassignments(handles)

    # Always flag reassigned resources as POSSIBLE leaks
    for rid in reassigned:
        if rid not in all_leaked:
            all_leaked.add(rid)

    # Build findings
    findings: list[Finding] = []
    seen: set[tuple[int, int, str]] = set()

    for rid in all_leaked:
        h = handles[rid]
        if h.is_safe_wrapped:
            continue

        key = (h.line, h.column, h.var_name)
        if key in seen:
            continue
        seen.add(key)

        confidence = Confidence.DEFINITE
        parts: list[str] = []

        if rid in arg_passed:
            confidence = Confidence.POSSIBLE
            parts.append(
                "resource is passed to another method which may close it"
            )

        if rid in reassigned:
            confidence = Confidence.POSSIBLE
            parts.append(
                "variable is conditionally reassigned; "
                "original resource may leak"
            )

        if rid in exception_leaked and rid not in leaked:
            parts.append(
                "resource is closed on the normal path but may leak if an "
                "exception is thrown; wrap in try-with-resources or use "
                "a finally block"
            )
        elif rid in leaked:
            parts.append(
                f"'{h.type_name}' opened as '{h.var_name}' is never closed"
                if rid not in reassigned and rid not in arg_passed
                else f"'{h.type_name}' may not be closed on all paths"
            )

        message = "; ".join(parts) if parts else (
            f"'{h.type_name}' opened as '{h.var_name}' "
            f"may not be closed on all paths"
        )

        findings.append(Finding(
            file_path=file_path,
            line=h.line,
            column=h.column,
            resource=h,
            confidence=confidence,
            message=message,
            method_name=method_name,
        ))

    return findings


# ------------------------------------------------------------------
# Forward dataflow analysis
# ------------------------------------------------------------------

def _forward_dataflow(
    cfg: CFG,
    handles: list[ResourceHandle],
    rules: LanguageRules,
) -> dict[int, dict[int, ResourceState]]:
    """Compute resource states at each block exit via worklist."""
    out_state: dict[int, dict[int, ResourceState]] = {
        bid: {} for bid in cfg.blocks
    }

    worklist = [cfg.entry_id]
    max_iters = len(cfg.blocks) * (len(handles) + 1) * 3 + 20

    for _ in range(max_iters):
        if not worklist:
            break
        bid = worklist.pop(0)
        block = cfg.blocks.get(bid)
        if block is None:
            continue

        # Merge predecessors
        if block.predecessors:
            pred_states = [
                out_state.get(p, {}) for p in block.predecessors
                if p in cfg.blocks
            ]
            in_state = _merge_states(pred_states)
        else:
            in_state = {}

        # Process block
        new_out = _process_block(block, in_state, handles, rules)

        if new_out != out_state[bid]:
            out_state[bid] = new_out
            for succ in block.successors:
                if succ not in worklist:
                    worklist.append(succ)

    return out_state


def _merge_states(
    states: list[dict[int, ResourceState]],
) -> dict[int, ResourceState]:
    """Merge states at a join point.  OPEN wins (conservative for leaks)."""
    if not states:
        return {}
    if len(states) == 1:
        return dict(states[0])

    merged: dict[int, ResourceState] = {}
    all_keys: set[int] = set()
    for s in states:
        all_keys.update(s.keys())

    for key in all_keys:
        values = [s[key] for s in states if key in s]
        if any(v == ResourceState.OPEN for v in values):
            merged[key] = ResourceState.OPEN
        else:
            merged[key] = ResourceState.CLOSED

    return merged


def _process_block(
    block,
    in_state: dict[int, ResourceState],
    handles: list[ResourceHandle],
    rules: LanguageRules,
) -> dict[int, ResourceState]:
    """Apply block's statements to the input state."""
    state = dict(in_state)

    for stmt in block.statements:
        # Acquisitions
        for rid, h in enumerate(handles):
            if _stmt_contains_acquisition(stmt, h):
                state[rid] = ResourceState.OPEN

        # Closes
        for var_name in _get_close_vars(stmt, rules):
            for rid, h in enumerate(handles):
                if h.var_name == var_name and state.get(rid) == ResourceState.OPEN:
                    state[rid] = ResourceState.CLOSED

    return state


def _stmt_contains_acquisition(stmt: Node, handle: ResourceHandle) -> bool:
    """Check if *stmt* contains the acquisition node for *handle*."""
    acq = handle.acquisition_node
    return stmt.start_byte <= acq.start_byte and acq.end_byte <= stmt.end_byte


def _get_close_vars(stmt: Node, rules: LanguageRules) -> set[str]:
    """Get variable names whose close() is called in *stmt*."""
    results: set[str] = set()
    for inv in _find_nodes_by_type(stmt, "method_invocation"):
        children = inv.children
        if len(children) >= 4:
            obj, dot, method = children[0], children[1], children[2]
            if (dot.type == "."
                    and obj.type == "identifier"
                    and method.type == "identifier"
                    and rules.is_release_method(method.text.decode("utf-8"))):
                results.add(obj.text.decode("utf-8"))
    return results


# ------------------------------------------------------------------
# Exception-path safety check
# ------------------------------------------------------------------

def _is_exception_safe(
    handle: ResourceHandle,
    cfg: CFG,
    rules: LanguageRules,
) -> bool:
    """Check whether a resource's close is exception-safe.

    Safe means:
    - The resource is in a try-with-resources block, OR
    - The close() is in a finally block, OR
    - There are no potentially-throwing statements between open and close
    """
    if handle.is_safe_wrapped:
        return True

    close_stmts = _find_all_close_stmts(handle.var_name, cfg, rules)
    if not close_stmts:
        return False

    # If any close is in a finally block → safe
    if any(_is_in_finally(cs) for cs, _ in close_stmts):
        return True

    # Check for throwing statements between acquisition and earliest close
    acq_line = handle.line
    earliest_close_line = min(
        cs.start_point[0] + 1 for cs, _ in close_stmts
    )

    if acq_line >= earliest_close_line:
        return True

    for block in cfg.blocks.values():
        for stmt in block.statements:
            stmt_line = stmt.start_point[0] + 1
            if acq_line < stmt_line < earliest_close_line:
                if _can_throw(stmt):
                    return False

    return True


def _find_all_close_stmts(
    var_name: str,
    cfg: CFG,
    rules: LanguageRules,
) -> list[tuple[Node, int]]:
    """Return all ``(statement_node, block_id)`` where *var_name*.close() is called."""
    results: list[tuple[Node, int]] = []
    for bid, block in cfg.blocks.items():
        for stmt in block.statements:
            if var_name in _get_close_vars(stmt, rules):
                results.append((stmt, bid))
    return results


def _is_in_finally(node: Node) -> bool:
    """Walk up the AST to check if *node* is inside a ``finally_clause``."""
    current = node.parent
    while current is not None:
        if current.type == "finally_clause":
            return True
        current = current.parent
    return False


def _can_throw(stmt: Node) -> bool:
    """Check if a statement could potentially throw an exception."""
    return (
        bool(_find_nodes_by_type(stmt, "method_invocation"))
        or bool(_find_nodes_by_type(stmt, "object_creation_expression"))
    )


# ------------------------------------------------------------------
# Confidence helpers
# ------------------------------------------------------------------

def _find_argument_passing(
    cfg: CFG,
    handles: list[ResourceHandle],
    rules: LanguageRules,
) -> set[int]:
    """Return resource IDs that are passed as arguments to non-release methods."""
    tracked_vars = {h.var_name for h in handles}
    passed: set[int] = set()

    for block in cfg.blocks.values():
        for stmt in block.statements:
            for inv in _find_nodes_by_type(stmt, "method_invocation"):
                # Skip release calls
                children = inv.children
                is_release = False
                if len(children) >= 4:
                    m = children[2]
                    if (m.type == "identifier"
                            and rules.is_release_method(m.text.decode("utf-8"))):
                        is_release = True
                if is_release:
                    continue

                # Check arguments
                for al in _find_nodes_by_type(inv, "argument_list"):
                    for arg in al.children:
                        if arg.type == "identifier":
                            vn = arg.text.decode("utf-8")
                            if vn in tracked_vars:
                                for rid, h in enumerate(handles):
                                    if h.var_name == vn:
                                        passed.add(rid)

    return passed


def _find_reassignments(handles: list[ResourceHandle]) -> set[int]:
    """Return resource IDs whose variable has multiple acquisitions.

    When a variable is used for two different acquisitions, earlier ones
    are considered "reassigned" and may leak.
    """
    var_counts: dict[str, list[int]] = defaultdict(list)
    for rid, h in enumerate(handles):
        var_counts[h.var_name].append(rid)

    reassigned: set[int] = set()
    for rids in var_counts.values():
        if len(rids) > 1:
            for rid in rids[:-1]:
                reassigned.add(rid)

    return reassigned
