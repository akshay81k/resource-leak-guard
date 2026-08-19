"""AST-guided Java source code rewriter for try-with-resources patch generation.

Converts leaked resource acquisitions into try-with-resources blocks.
"""

from __future__ import annotations

from typing import Optional
from tree_sitter import Node

from src.models import Finding
from src.parser.ast_loader import parse_bytes


def rewrite_leak_to_try_with_resources(
    source_bytes: bytes,
    finding: Finding,
) -> Optional[str]:
    """Rewrite Java source code to wrap a leaked resource in try-with-resources.

    Args:
        source_bytes: Original UTF-8 source bytes.
        finding: Finding containing the ResourceHandle and location.

    Returns:
        The rewritten source code as a string, or None if automated rewrite
        is not supported.
    """
    if finding.confidence != finding.confidence.DEFINITE:
        return None

    try:
        tree = parse_bytes(source_bytes)
    except Exception:
        return None

    handle = finding.resource
    var_name = handle.var_name
    type_name = handle.type_name

    # Find target local_variable_declaration node at finding line
    decl_node = _find_declaration_node(tree.root_node, handle.line, var_name)
    if decl_node is None:
        return None

    # Get enclosing block
    block_node = decl_node.parent
    if block_node is None or block_node.type != "block":
        return None

    block_children = [c for c in block_node.children if c.type not in ("{", "}")]
    try:
        decl_idx = block_children.index(decl_node)
    except ValueError:
        return None

    # Check for explicit close() statement later in block
    close_node = _find_close_statement(block_children[decl_idx + 1:], var_name)

    # Detect line ending style (\r\n vs \n)
    source_text = source_bytes.decode("utf-8")
    line_ending = "\r\n" if "\r\n" in source_text else "\n"
    lines = source_text.splitlines()

    # Determine indentation of declaration line
    decl_line_idx = handle.line - 1
    decl_line_text = lines[decl_line_idx]
    indent = decl_line_text[: len(decl_line_text) - len(decl_line_text.lstrip())]
    inner_indent = indent + "    "

    # Extract object creation expression
    acq_node = handle.acquisition_node
    acq_text = acq_node.text.decode("utf-8")

    # Determine statement range to wrap inside try block
    if close_node is not None:
        try:
            close_idx = block_children.index(close_node)
        except ValueError:
            close_idx = len(block_children)
        stmts_to_wrap = block_children[decl_idx + 1 : close_idx]
        end_stmt_node = close_node
    else:
        stmts_to_wrap = block_children[decl_idx + 1 :]
        end_stmt_node = block_children[-1] if block_children else decl_node

    start_line_idx = decl_node.start_point[0]
    end_line_idx = end_stmt_node.end_point[0]

    # Format try-with-resources block
    new_block_lines: list[str] = []
    new_block_lines.append(f"{indent}try ({type_name} {var_name} = {acq_text}) {{")

    if stmts_to_wrap:
        for stmt in stmts_to_wrap:
            stmt_start = stmt.start_point[0]
            stmt_end = stmt.end_point[0]
            for l_idx in range(stmt_start, stmt_end + 1):
                raw_line = lines[l_idx].strip()
                if raw_line:
                    new_block_lines.append(f"{inner_indent}{raw_line}")

    new_block_lines.append(f"{indent}}}")

    # Reconstruct whole file preserving original line ending
    new_lines = (
        lines[:start_line_idx]
        + new_block_lines
        + lines[end_line_idx + 1 :]
    )

    result = line_ending.join(new_lines)
    if source_text.endswith("\n") or source_text.endswith("\r\n"):
        result += line_ending
    return result


def _find_declaration_node(root: Node, line: int, var_name: str) -> Optional[Node]:
    """Find local_variable_declaration node at given line for var_name."""
    candidates: list[Node] = []

    def _visit(n: Node):
        if n.type == "local_variable_declaration" and (n.start_point[0] + 1) == line:
            candidates.append(n)
        for c in n.children:
            _visit(c)

    _visit(root)
    for cand in candidates:
        for child in cand.children:
            if child.type == "variable_declarator":
                name_n = child.child_by_field_name("name")
                if name_n and name_n.text.decode("utf-8") == var_name:
                    return cand
    return candidates[0] if candidates else None


def _find_close_statement(statements: list[Node], var_name: str) -> Optional[Node]:
    """Find statement node that calls var_name.close()."""
    for stmt in statements:
        found = False
        def _check(n: Node):
            nonlocal found
            if n.type == "method_invocation":
                ch = n.children
                if len(ch) >= 4 and ch[0].text.decode("utf-8") == var_name:
                    if ch[2].text.decode("utf-8") == "close":
                        found = True
            for c in n.children:
                _check(c)
        _check(stmt)
        if found:
            return stmt
    return None
