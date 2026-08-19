"""Go patch rewriter that inserts `defer var.Close()` after acquisition and error check."""

from __future__ import annotations

from typing import Optional
from src.models import Finding
from src.parser.ast_loader_go import parse_go_bytes


def rewrite_go_leak(
    source_bytes: bytes,
    finding: Finding,
) -> Optional[str]:
    """Insert `defer var.Close()` after the acquisition / error check line in Go."""
    source_text = source_bytes.decode("utf-8")
    lines = source_text.splitlines()

    acq_line_idx = finding.line - 1
    if acq_line_idx >= len(lines):
        return None

    var_name = finding.resource.var_name

    # Determine insertion point (after error check `if err != nil { ... }` if present)
    insert_line_idx = acq_line_idx + 1
    if insert_line_idx < len(lines) and "if err != nil" in lines[insert_line_idx]:
        # Skip until closing brace of if statement
        while insert_line_idx < len(lines) and "}" not in lines[insert_line_idx]:
            insert_line_idx += 1
        insert_line_idx += 1

    # Match indent of acquisition line
    acq_line = lines[acq_line_idx]
    indent = acq_line[: len(acq_line) - len(acq_line.lstrip())]

    defer_stmt = f"{indent}defer {var_name}.Close()"

    new_lines = (
        lines[:insert_line_idx]
        + [defer_stmt]
        + lines[insert_line_idx:]
    )

    result = "\n".join(new_lines)
    if source_text.endswith("\n"):
        result += "\n"
    return result
