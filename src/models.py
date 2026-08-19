"""Shared dataclasses for the resource-leak-guard static analyzer.

All core types used across the pipeline — AST loading, CFG construction,
resource tracking, leak detection, and patch generation — are defined here
to avoid circular imports and keep the data model in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Confidence levels for findings
# ---------------------------------------------------------------------------

class Confidence(Enum):
    """How certain we are that a finding is a real leak.

    DEFINITE means all paths were traced, the resource type is a known
    closeable, and there is no reassignment.  The build should fail.

    POSSIBLE means the resource may be reassigned conditionally or passed
    to another method.  The build should warn, not fail.
    """
    DEFINITE = auto()
    POSSIBLE = auto()


# ---------------------------------------------------------------------------
# Resource state used during dataflow analysis
# ---------------------------------------------------------------------------

class ResourceState(Enum):
    """Tracks the open/closed state of a single resource variable."""
    OPEN = auto()
    CLOSED = auto()
    UNKNOWN = auto()


# ---------------------------------------------------------------------------
# AST-level resource information
# ---------------------------------------------------------------------------

@dataclass
class ResourceHandle:
    """A single resource acquisition site discovered in the source code.

    Attributes:
        var_name:        The variable name that holds the resource.
        type_name:       The type being constructed (e.g. ``FileInputStream``).
        acquisition_node: The tree-sitter AST node for the acquisition
                         expression (the ``new Xxx(...)`` call).
        line:            1-based line number of the acquisition.
        column:          0-based column offset of the acquisition.
        state:           Current open/closed state (set during analysis).
        is_safe_wrapped: ``True`` when the resource is inside a
                         try-with-resources block.
    """
    var_name: str
    type_name: str
    acquisition_node: Any  # tree_sitter.Node — kept as Any to avoid coupling
    line: int
    column: int
    state: ResourceState = ResourceState.OPEN
    is_safe_wrapped: bool = False


# ---------------------------------------------------------------------------
# Control-Flow Graph
# ---------------------------------------------------------------------------

@dataclass
class BasicBlock:
    """One basic block inside a control-flow graph.

    A basic block is a maximal sequence of statements with a single entry
    point and a single exit point (no internal branching).

    Attributes:
        id:          Unique integer identifier within the owning CFG.
        statements:  Ordered list of tree-sitter AST nodes in this block.
        successors:  IDs of successor blocks (outgoing edges).
        predecessors: IDs of predecessor blocks (incoming edges).
        is_exit:     ``True`` if this block is a function exit point.
    """
    id: int
    statements: list[Any] = field(default_factory=list)
    successors: list[int] = field(default_factory=list)
    predecessors: list[int] = field(default_factory=list)
    is_exit: bool = False


@dataclass
class CFG:
    """A per-method control-flow graph.

    Attributes:
        blocks:    Mapping from block ID → BasicBlock.
        entry_id:  ID of the entry basic block.
        exit_ids:  Set of block IDs that represent function exits.
        method_node: The tree-sitter method_declaration node this CFG
                     was built from.
    """
    blocks: dict[int, BasicBlock] = field(default_factory=dict)
    entry_id: int = 0
    exit_ids: set[int] = field(default_factory=set)
    method_node: Any = None  # tree_sitter.Node

    def get_block(self, block_id: int) -> Optional[BasicBlock]:
        """Return the block with the given ID, or ``None``."""
        return self.blocks.get(block_id)


# ---------------------------------------------------------------------------
# Findings (the output of analysis)
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    """A detected resource leak or potential leak.

    Attributes:
        file_path:   Path to the source file.
        line:        1-based line number of the acquisition.
        column:      0-based column offset.
        resource:    The ``ResourceHandle`` that leaks.
        confidence:  ``DEFINITE`` or ``POSSIBLE``.
        message:     Human-readable explanation of the leak.
        method_name: Name of the enclosing method.
    """
    file_path: str
    line: int
    column: int
    resource: ResourceHandle
    confidence: Confidence
    message: str
    method_name: str = ""
