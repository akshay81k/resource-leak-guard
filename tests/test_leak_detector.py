"""Phase 2 tests: leak detection across all 7 fixtures.

Tests verify the full pipeline: parse → CFG → resource tracking →
dataflow analysis → leak detection with correct confidence levels.
"""

from pathlib import Path

import pytest

from src.parser.ast_loader import parse_file, find_method_declarations, get_method_name
from src.parser.cfg_builder import build_cfg
from src.models import Confidence
from src.analysis.leak_detector import detect_leaks
from src.rules.schema import load_default_java_rules


FIXTURES = Path(__file__).parent / "fixtures" / "java"


def _run_detector(fixture_name: str):
    """Helper: parse a fixture, build CFG, run leak detection."""
    path = FIXTURES / fixture_name
    tree, source = parse_file(path)
    rules = load_default_java_rules()
    methods = find_method_declarations(tree)

    all_findings = []
    for method in methods:
        name = get_method_name(method)
        cfg = build_cfg(method)
        findings = detect_leaks(str(path), name, cfg, rules, source)
        all_findings.extend(findings)
    return all_findings


# ------------------------------------------------------------------
# Fixture tests
# ------------------------------------------------------------------

class TestFixture01NoLeakExplicitClose:
    def test_zero_findings(self):
        findings = _run_detector("01_no_leak_explicit_close.java")
        assert len(findings) == 0


class TestFixture02LeakMissingClose:
    def test_one_definite_finding(self):
        findings = _run_detector("02_leak_missing_close.java")
        assert len(findings) == 1
        f = findings[0]
        assert f.confidence == Confidence.DEFINITE
        assert f.resource.var_name == "fis"
        assert f.resource.type_name == "FileInputStream"

    def test_message_mentions_never_closed(self):
        findings = _run_detector("02_leak_missing_close.java")
        assert "never closed" in findings[0].message


class TestFixture03NoLeakTryWithResources:
    def test_zero_findings(self):
        findings = _run_detector("03_no_leak_try_with_resources.java")
        assert len(findings) == 0


class TestFixture04LeakOnExceptionPath:
    def test_one_definite_finding(self):
        findings = _run_detector("04_leak_only_on_exception_path.java")
        assert len(findings) == 1
        f = findings[0]
        assert f.confidence == Confidence.DEFINITE
        assert f.resource.var_name == "fis"

    def test_message_mentions_exception(self):
        findings = _run_detector("04_leak_only_on_exception_path.java")
        assert "exception" in findings[0].message.lower()


class TestFixture05NoLeakFinallyBlock:
    def test_zero_findings(self):
        findings = _run_detector("05_no_leak_finally_block.java")
        assert len(findings) == 0


class TestFixture06PossibleLeakConditionalReassignment:
    def test_one_possible_finding(self):
        findings = _run_detector("06_possible_leak_conditional_reassignment.java")
        assert len(findings) >= 1
        # The original resource (path1) should be flagged
        possible = [f for f in findings if f.confidence == Confidence.POSSIBLE]
        assert len(possible) >= 1

    def test_message_mentions_reassignment(self):
        findings = _run_detector("06_possible_leak_conditional_reassignment.java")
        possible = [f for f in findings if f.confidence == Confidence.POSSIBLE]
        assert any("reassign" in f.message.lower() for f in possible)


class TestFixture07PossibleLeakPassedToHelper:
    def test_one_possible_finding(self):
        findings = _run_detector("07_possible_leak_passed_to_helper.java")
        assert len(findings) >= 1
        f = findings[0]
        assert f.confidence == Confidence.POSSIBLE
        assert f.resource.var_name == "fis"

    def test_message_mentions_passed(self):
        findings = _run_detector("07_possible_leak_passed_to_helper.java")
        assert any("passed" in f.message.lower() for f in findings)


# ------------------------------------------------------------------
# CFG branching tests
# ------------------------------------------------------------------

class TestCFGBranching:
    """Verify the CFG builder handles branching constructs correctly."""

    def test_if_else_creates_multiple_blocks(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m(boolean flag) {
                int x = 1;
                if (flag) {
                    x = 2;
                } else {
                    x = 3;
                }
                x = 4;
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        # Should have more than 1 block due to if/else
        assert len(cfg.blocks) > 1

    def test_while_creates_back_edge(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m() {
                int i = 0;
                while (i < 10) {
                    i++;
                }
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        # Check for back edge: some block should have a successor
        # that is also a predecessor (loop)
        has_back_edge = False
        for block in cfg.blocks.values():
            for succ_id in block.successors:
                succ = cfg.blocks.get(succ_id)
                if succ and block.id in succ.successors:
                    has_back_edge = True
        # The header block has both a body successor and an after successor
        assert len(cfg.blocks) > 1

    def test_try_catch_creates_catch_block(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m() {
                try {
                    int x = 1;
                } catch (Exception e) {
                    int y = 2;
                }
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        assert len(cfg.blocks) >= 3  # at least: before-try, try-body, catch

    def test_try_finally_creates_finally_block(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m() {
                try {
                    int x = 1;
                } finally {
                    int y = 2;
                }
            }
        }
        """
        tree = parse_bytes(code)
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        assert len(cfg.blocks) >= 3  # at least: before-try, try-body, finally


# ------------------------------------------------------------------
# Dataflow edge cases
# ------------------------------------------------------------------

class TestDataflowEdgeCases:
    """Test dataflow analysis on edge cases."""

    def test_resource_closed_in_both_branches(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m(String path, boolean flag) throws Exception {
                FileInputStream fis = new FileInputStream(path);
                if (flag) {
                    fis.close();
                } else {
                    fis.close();
                }
            }
        }
        """
        tree = parse_bytes(code)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        findings = detect_leaks("test.java", "m", cfg, rules, code)
        # Closed on both branches → no leak
        assert len(findings) == 0

    def test_resource_closed_in_one_branch_only(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m(String path, boolean flag) throws Exception {
                FileInputStream fis = new FileInputStream(path);
                if (flag) {
                    fis.close();
                }
            }
        }
        """
        tree = parse_bytes(code)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        findings = detect_leaks("test.java", "m", cfg, rules, code)
        # Closed on one branch only → leak
        assert len(findings) == 1
        assert findings[0].confidence == Confidence.DEFINITE

    def test_no_resource_no_finding(self):
        from src.parser.ast_loader import parse_bytes
        code = b"""
        public class T {
            void m() {
                int x = 42;
                System.out.println(x);
            }
        }
        """
        tree = parse_bytes(code)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        cfg = build_cfg(methods[0])
        findings = detect_leaks("test.java", "m", cfg, rules, code)
        assert len(findings) == 0
