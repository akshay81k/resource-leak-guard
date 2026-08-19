"""Track resource acquisitions and their state within a CFG.

Handles local variable declarations (both constructors and factory methods),
assignment expressions (for reassignment detection), and try-with-resources
resource nodes. Also detects close calls and argument-passing of tracked resources.
"""

from __future__ import annotations

from tree_sitter import Node

from src.models import BasicBlock, CFG, ResourceHandle, ResourceState
from src.rules.schema import LanguageRules


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _find_nodes_by_type(node: Node, target_type: str) -> list[Node]:
    """Recursively collect all descendant nodes of *target_type*."""
    results: list[Node] = []

    def _walk(n: Node) -> None:
        if n.type == target_type:
            results.append(n)
        for child in n.children:
            _walk(child)

    _walk(node)
    return results


def _get_var_name_for_declaration(stmt: Node) -> str | None:
    """Extract the variable name from a ``local_variable_declaration``."""
    for child in stmt.children:
        if child.type == "variable_declarator":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                return name_node.text.decode("utf-8")
    return None


def _get_declared_type_name(stmt: Node) -> str | None:
    """Return the declared type name from a local_variable_declaration or object creation."""
    # First check explicit declared type (e.g. Connection, FileInputStream, Socket)
    t_node = stmt.child_by_field_name("type")
    if t_node is not None:
        type_text = t_node.text.decode("utf-8")
        if type_text:
            return type_text

    # Fallback to object creation expression (new Xxx(...))
    for oce in _find_nodes_by_type(stmt, "object_creation_expression"):
        type_node = oce.child_by_field_name("type")
        if type_node is None:
            for child in oce.children:
                if child.type == "type_identifier":
                    return child.text.decode("utf-8")
        else:
            return type_node.text.decode("utf-8")
    return None


def _get_acquisition_node(stmt: Node) -> Node:
    """Return the acquisition node (value expression or statement)."""
    for child in stmt.children:
        if child.type == "variable_declarator":
            val_node = child.child_by_field_name("value")
            if val_node is not None:
                return val_node
    nodes = _find_nodes_by_type(stmt, "object_creation_expression")
    return nodes[0] if nodes else stmt


def _is_inside_safe_wrapper(node: Node, rules: LanguageRules) -> bool:
    """Walk up the AST from *node* and check if it's inside a
    try-with-resources ``resource`` node."""
    current = node.parent
    while current is not None:
        if current.type == "resource":
            return True
        current = current.parent
    return False


def _find_close_calls(stmt: Node, rules: LanguageRules) -> list[tuple[str, Node]]:
    """Find ``var.close()`` calls in *stmt*.

    Returns a list of ``(var_name, method_invocation_node)`` tuples.
    """
    results: list[tuple[str, Node]] = []
    for invocation in _find_nodes_by_type(stmt, "method_invocation"):
        children = invocation.children
        if len(children) >= 4:
            obj_node = children[0]
            dot_node = children[1]
            method_node = children[2]
            if (
                dot_node.type == "."
                and obj_node.type == "identifier"
                and method_node.type == "identifier"
                and rules.is_release_method(method_node.text.decode("utf-8"))
            ):
                var_name = obj_node.text.decode("utf-8")
                results.append((var_name, invocation))
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def track_resources(
    cfg: CFG,
    rules: LanguageRules,
    source_bytes: bytes,
) -> list[ResourceHandle]:
    """Scan a CFG for resource acquisitions and mark their initial state."""
    handles: list[ResourceHandle] = []
    handle_by_name: dict[str, ResourceHandle] = {}

    # --- Pass 1: find acquisitions ----------------------------------------
    for block in cfg.blocks.values():
        for stmt in block.statements:
            _scan_statement_for_acquisitions(
                stmt, rules, handles, handle_by_name
            )

    # --- Pass 2: find release calls and mark CLOSED -----------------------
    for block in cfg.blocks.values():
        for stmt in block.statements:
            close_calls = _find_close_calls(stmt, rules)
            for var_name, _ in close_calls:
                if var_name in handle_by_name:
                    handle_by_name[var_name].state = ResourceState.CLOSED

    return handles


# ---------------------------------------------------------------------------
# Acquisition scanning
# ---------------------------------------------------------------------------

def _scan_statement_for_acquisitions(
    stmt: Node,
    rules: LanguageRules,
    handles: list[ResourceHandle],
    handle_by_name: dict[str, ResourceHandle],
) -> None:
    """Check a single statement for resource acquisitions."""

    if stmt.type == "local_variable_declaration":
        _scan_local_var_decl(stmt, rules, handles, handle_by_name)
    elif stmt.type == "expression_statement":
        _scan_expression_stmt(stmt, rules, handles, handle_by_name)
    elif stmt.type == "resource_specification":
        _scan_resource_spec(stmt, rules, handles, handle_by_name)


def _scan_local_var_decl(
    stmt: Node,
    rules: LanguageRules,
    handles: list[ResourceHandle],
    handle_by_name: dict[str, ResourceHandle],
) -> None:
    """Scan a local_variable_declaration for resource acquisitions."""
    type_name = _get_declared_type_name(stmt)
    if type_name is None or not rules.is_acquisition_type(type_name):
        return

    var_name = _get_var_name_for_declaration(stmt)
    if var_name is None:
        return

    acq_node = _get_acquisition_node(stmt)
    is_safe = _is_inside_safe_wrapper(acq_node, rules)
    line = acq_node.start_point[0] + 1
    column = acq_node.start_point[1]

    handle = ResourceHandle(
        var_name=var_name,
        type_name=type_name,
        acquisition_node=acq_node,
        line=line,
        column=column,
        state=ResourceState.OPEN,
        is_safe_wrapped=is_safe,
    )
    handles.append(handle)
    handle_by_name[var_name] = handle


def _scan_expression_stmt(
    stmt: Node,
    rules: LanguageRules,
    handles: list[ResourceHandle],
    handle_by_name: dict[str, ResourceHandle],
) -> None:
    """Scan an expression_statement for assignment-based acquisitions."""
    for assign in _find_nodes_by_type(stmt, "assignment_expression"):
        children = assign.children
        if len(children) < 3:
            continue

        lhs = children[0]
        rhs = children[2]

        if lhs.type != "identifier":
            continue

        var_name = lhs.text.decode("utf-8")

        acq_node = rhs
        type_name = None
        for oce in _find_nodes_by_type(rhs, "object_creation_expression"):
            for child in oce.children:
                if child.type == "type_identifier":
                    type_name = child.text.decode("utf-8")
                    break

        if type_name is None or not rules.is_acquisition_type(type_name):
            continue

        line = acq_node.start_point[0] + 1
        column = acq_node.start_point[1]

        handle = ResourceHandle(
            var_name=var_name,
            type_name=type_name,
            acquisition_node=acq_node,
            line=line,
            column=column,
            state=ResourceState.OPEN,
            is_safe_wrapped=False,
        )
        handles.append(handle)
        handle_by_name[var_name] = handle


def _scan_resource_spec(
    stmt: Node,
    rules: LanguageRules,
    handles: list[ResourceHandle],
    handle_by_name: dict[str, ResourceHandle],
) -> None:
    """Scan a resource_specification for try-with-resources acquisitions."""
    for child in stmt.children:
        if child.type != "resource":
            continue

        var_name = None
        type_name = None
        acq_node = None

        for rchild in child.children:
            if rchild.type == "identifier" and var_name is None:
                var_name = rchild.text.decode("utf-8")
            elif rchild.type == "type_identifier" and type_name is None:
                type_name = rchild.text.decode("utf-8")

        oce_nodes = _find_nodes_by_type(child, "object_creation_expression")
        if oce_nodes:
            acq_node = oce_nodes[0]
            for oce_child in acq_node.children:
                if oce_child.type == "type_identifier":
                    type_name = oce_child.text.decode("utf-8")
                    break

        if (type_name is None or var_name is None
                or not rules.is_acquisition_type(type_name)):
            continue

        if acq_node is None:
            acq_node = child

        handle = ResourceHandle(
            var_name=var_name,
            type_name=type_name,
            acquisition_node=acq_node,
            line=child.start_point[0] + 1,
            column=child.start_point[1],
            state=ResourceState.OPEN,
            is_safe_wrapped=True,  # try-with-resources!
        )
        handles.append(handle)
        handle_by_name[var_name] = handle
