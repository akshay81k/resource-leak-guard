"""AST loader for Go using tree-sitter-go."""

from __future__ import annotations

from pathlib import Path
from typing import Union

import tree_sitter_go as tsgo
from tree_sitter import Language, Parser, Node, Tree


GO_LANGUAGE = Language(tsgo.language())
_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        _parser = Parser(GO_LANGUAGE)
    return _parser


def parse_go_file(path: Union[str, Path]) -> tuple[Tree, bytes]:
    p = Path(path)
    source_bytes = p.read_bytes()
    tree = parse_go_bytes(source_bytes)
    return tree, source_bytes


def parse_go_bytes(source: bytes) -> Tree:
    parser = _get_parser()
    return parser.parse(source)


def find_go_function_declarations(tree: Tree) -> list[Node]:
    funcs: list[Node] = []
    def _visit(n: Node):
        if n.type == "function_declaration":
            funcs.append(n)
        for c in n.children:
            _visit(c)
    _visit(tree.root_node)
    return funcs


def get_go_function_name(func_node: Node) -> str:
    name_n = func_node.child_by_field_name("name")
    return name_n.text.decode("utf-8") if name_n else "<unknown>"
