"""AST loading and method extraction using tree-sitter with the Java grammar.

This module provides the entry point for parsing Java source files into
tree-sitter syntax trees and extracting method declaration nodes so they
can be fed into the CFG builder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node, Tree


# ---------------------------------------------------------------------------
# Language / parser singletons (loaded once, reused across calls)
# ---------------------------------------------------------------------------

JAVA_LANGUAGE = Language(tsjava.language())

_parser: Parser | None = None


def _get_parser() -> Parser:
    """Return a lazily-initialised tree-sitter parser for Java."""
    global _parser
    if _parser is None:
        _parser = Parser(JAVA_LANGUAGE)
    return _parser


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_file(path: Union[str, Path]) -> tuple[Tree, bytes]:
    """Parse a ``.java`` file and return the tree + source bytes.

    Args:
        path: Filesystem path to the Java source file.

    Returns:
        A ``(tree, source_bytes)`` tuple.  The source bytes are needed by
        downstream code for byte-offset → text lookups and for the patch
        generator.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If tree-sitter reports parse errors at the root level.
    """
    p = Path(path)
    source_bytes = p.read_bytes()
    tree = parse_bytes(source_bytes)
    return tree, source_bytes


def parse_bytes(source: bytes) -> Tree:
    """Parse raw Java source bytes and return the tree-sitter ``Tree``.

    Args:
        source: UTF-8 encoded Java source code.

    Returns:
        The parsed ``Tree``.

    Raises:
        ValueError: If the root node has errors.
    """
    parser = _get_parser()
    tree = parser.parse(source)
    if tree.root_node.has_error:
        # Collect first few error nodes for a useful message
        errors = _collect_errors(tree.root_node, limit=5)
        msg = "; ".join(errors) if errors else "unknown parse error"
        raise ValueError(f"Parse errors in source: {msg}")
    return tree


def find_method_declarations(tree: Tree) -> list[Node]:
    """Return all ``method_declaration`` nodes in the tree.

    Walks the full AST (all classes, inner classes, etc.) and returns
    every method declaration found, in document order.
    """
    methods: list[Node] = []
    _walk_for_type(tree.root_node, "method_declaration", methods)
    return methods


def find_class_declarations(tree: Tree) -> list[Node]:
    """Return all ``class_declaration`` nodes in the tree."""
    classes: list[Node] = []
    _walk_for_type(tree.root_node, "class_declaration", classes)
    return classes


def get_method_name(method_node: Node) -> str:
    """Extract the method name from a ``method_declaration`` node."""
    name_node = method_node.child_by_field_name("name")
    if name_node is not None:
        return name_node.text.decode("utf-8")
    return "<unknown>"


def get_method_body(method_node: Node) -> Node | None:
    """Return the ``block`` node that is the method body, or ``None``."""
    return method_node.child_by_field_name("body")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _walk_for_type(node: Node, target_type: str, acc: list[Node]) -> None:
    """Depth-first walk collecting all nodes of *target_type*."""
    if node.type == target_type:
        acc.append(node)
    for child in node.children:
        _walk_for_type(child, target_type, acc)


def _collect_errors(node: Node, limit: int = 5) -> list[str]:
    """Collect human-readable descriptions of parse-error nodes."""
    errors: list[str] = []

    def _visit(n: Node) -> None:
        if len(errors) >= limit:
            return
        if n.type == "ERROR" or n.is_missing:
            row, col = n.start_point
            errors.append(f"line {row + 1}:{col}")
        for child in n.children:
            _visit(child)

    _visit(node)
    return errors
