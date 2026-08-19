"""Unified diff writer for patch generation.

Produces git-apply compatible patch strings from original and rewritten text.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Optional

from src.models import Finding
from src.patch.java_rewriter import rewrite_leak_to_try_with_resources


def generate_patch(
    file_path: str,
    source_bytes: bytes,
    finding: Finding,
) -> Optional[str]:
    """Generate a unified diff patch string for a resource leak finding.

    Args:
        file_path: Relative or absolute path to the source file.
        source_bytes: Original file contents as bytes.
        finding: Finding instance describing the leak.

    Returns:
        A unified diff string, or None if patch generation is not applicable.
    """
    rewritten = rewrite_leak_to_try_with_resources(source_bytes, finding)
    if rewritten is None:
        return None

    original_text = source_bytes.decode("utf-8")
    if original_text == rewritten:
        return None

    file_name = Path(file_path).name
    a_path = f"a/{file_name}"
    b_path = f"b/{file_name}"

    orig_lines = original_text.splitlines(keepends=True)
    mod_lines = rewritten.splitlines(keepends=True)

    diff_lines = list(
        difflib.unified_diff(
            orig_lines,
            mod_lines,
            fromfile=a_path,
            tofile=b_path,
            n=3,
        )
    )

    if not diff_lines:
        return None

    return "".join(diff_lines)
