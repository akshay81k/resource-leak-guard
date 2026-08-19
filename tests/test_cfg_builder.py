"""Phase 1 tests: AST parsing, CFG construction, and resource tracking.

These tests verify the core pipeline:
  1. Parse a Java file with tree-sitter
  2. Extract method declarations
  3. Build a linear CFG
  4. Identify resource acquisition sites and their state
"""

from pathlib import Path

import pytest

from src.parser.ast_loader import (
    parse_file,
    parse_bytes,
    find_method_declarations,
    get_method_name,
    get_method_body,
)
from src.parser.cfg_builder import build_cfg
from src.models import ResourceState
from src.analysis.resource_tracker import track_resources
from src.rules.schema import load_default_java_rules


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "java"


# ---------------------------------------------------------------------------
# AST Loader tests
# ---------------------------------------------------------------------------

class TestASTLoader:
    """Tests for ``ast_loader.py``."""

    def test_parse_file_returns_tree_and_bytes(self):
        """parse_file should return a (tree, bytes) tuple."""
        tree, source = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        assert tree is not None
        assert isinstance(source, bytes)
        assert b"FileInputStream" in source

    def test_parse_bytes_with_valid_java(self):
        """parse_bytes should parse valid Java without errors."""
        code = b"public class A { void m() {} }"
        tree = parse_bytes(code)
        assert tree.root_node.type == "program"

    def test_parse_bytes_with_invalid_java_raises(self):
        """parse_bytes should raise ValueError on broken syntax."""
        code = b"public class { void m( {{{ }"
        with pytest.raises(ValueError, match="Parse errors"):
            parse_bytes(code)

    def test_find_method_declarations(self):
        """find_method_declarations should find the leakyMethod."""
        tree, _ = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        assert len(methods) == 1
        assert get_method_name(methods[0]) == "leakyMethod"

    def test_get_method_body(self):
        """get_method_body should return the block node."""
        tree, _ = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        body = get_method_body(methods[0])
        assert body is not None
        assert body.type == "block"

    def test_find_multiple_methods(self):
        """find_method_declarations should find all methods in a class."""
        code = b"""
        public class Multi {
            void a() {}
            void b() {}
            void c() {}
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        assert len(methods) == 3
        names = {get_method_name(m) for m in methods}
        assert names == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# CFG Builder tests
# ---------------------------------------------------------------------------

class TestCFGBuilder:
    """Tests for ``cfg_builder.py``."""

    def test_linear_cfg_has_one_block(self):
        """A method with no branching should produce a single-block CFG."""
        tree, _ = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])

        assert len(cfg.blocks) == 1
        assert cfg.entry_id in cfg.blocks
        assert cfg.entry_id in cfg.exit_ids

    def test_linear_cfg_captures_statements(self):
        """The single block should contain all statements from the method body."""
        tree, _ = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])

        entry_block = cfg.blocks[cfg.entry_id]
        # leakyMethod has 3 statements:
        #   FileInputStream fis = new FileInputStream(path);
        #   int data = fis.read();
        #   System.out.println(data);
        assert len(entry_block.statements) == 3

    def test_cfg_with_return_creates_exit(self):
        """A return statement should mark the block as an exit."""
        code = b"""
        public class R {
            int getValue() {
                int x = 42;
                return x;
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])

        # Should have exactly one block (statements + return in same block)
        assert len(cfg.blocks) == 1
        exit_block = cfg.blocks[list(cfg.exit_ids)[0]]
        assert exit_block.is_exit

    def test_cfg_entry_is_exit_for_simple_method(self):
        """For a linear method, the entry block IS the exit block."""
        tree, _ = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        assert cfg.entry_id in cfg.exit_ids

    def test_empty_method_produces_single_exit_block(self):
        """An empty method body should still produce a valid single-block CFG."""
        code = b"public class E { void empty() {} }"
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])

        assert len(cfg.blocks) == 1
        assert cfg.entry_id in cfg.exit_ids


# ---------------------------------------------------------------------------
# Resource Tracker tests
# ---------------------------------------------------------------------------

class TestResourceTracker:
    """Tests for ``resource_tracker.py``."""

    def setup_method(self):
        """Load Java rules once for all tests in this class."""
        self.rules = load_default_java_rules()

    def test_identifies_leaky_file_input_stream(self):
        """The acceptance test: identify a leaked FileInputStream."""
        tree, source = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source)

        assert len(handles) == 1
        h = handles[0]
        assert h.var_name == "fis"
        assert h.type_name == "FileInputStream"
        assert h.state == ResourceState.OPEN
        assert h.is_safe_wrapped is False
        # Line should be correct (1-based)
        assert h.line > 0
        assert h.column >= 0

    def test_identifies_explicit_close(self):
        """A resource that is closed should be marked CLOSED."""
        tree, source = parse_file(FIXTURES_DIR / "phase1_explicit_close.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source)

        assert len(handles) == 1
        h = handles[0]
        assert h.var_name == "fis"
        assert h.type_name == "FileInputStream"
        assert h.state == ResourceState.CLOSED

    def test_no_resources_in_plain_method(self):
        """A method with no resource acquisitions should return empty list."""
        code = b"""
        public class Plain {
            void noResources() {
                int x = 42;
                System.out.println(x);
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source_bytes=code)

        assert len(handles) == 0

    def test_unknown_type_not_tracked(self):
        """A new SomeUnknownType() should NOT be tracked as a resource."""
        code = b"""
        public class Unknown {
            void method() {
                SomeUnknownType obj = new SomeUnknownType();
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source_bytes=code)

        assert len(handles) == 0

    def test_multiple_resources(self):
        """Multiple resources in one method should all be tracked."""
        code = b"""
        public class Multi {
            void method(String path) throws Exception {
                FileInputStream fis = new FileInputStream(path);
                BufferedReader br = new BufferedReader(null);
                int data = fis.read();
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source_bytes=code)

        assert len(handles) == 2
        names = {h.var_name for h in handles}
        assert "fis" in names
        assert "br" in names

    def test_acquisition_line_and_column(self):
        """Line and column of the acquisition should be correctly reported."""
        tree, source = parse_file(FIXTURES_DIR / "phase1_leaky_method.java")
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        handles = track_resources(cfg, self.rules, source)

        h = handles[0]
        # "new FileInputStream(path)" is on line 5 of the fixture file
        # (1-based: line 1 = import, line 2 = blank, line 3 = class, line 4 = method, line 5 = fis)
        assert h.line == 5
        # Column should point to the "new" keyword
        assert h.column > 0


# ---------------------------------------------------------------------------
# Rule schema tests
# ---------------------------------------------------------------------------

class TestRuleSchema:
    """Tests for ``schema.py``."""

    def test_load_default_java_rules(self):
        """Loading the built-in java.yaml should succeed."""
        rules = load_default_java_rules()
        assert rules.language == "java"
        assert len(rules.acquisitions) > 0
        assert len(rules.releases) > 0
        assert len(rules.safe_wrappers) > 0

    def test_file_input_stream_is_acquisition(self):
        """FileInputStream should be a known acquisition type."""
        rules = load_default_java_rules()
        assert rules.is_acquisition_type("FileInputStream")

    def test_close_is_release(self):
        """close() should be a known release method."""
        rules = load_default_java_rules()
        assert rules.is_release_method("close")

    def test_unknown_type_is_not_acquisition(self):
        """An unknown type should not be treated as an acquisition."""
        rules = load_default_java_rules()
        assert not rules.is_acquisition_type("StringBuilder")
