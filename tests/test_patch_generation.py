"""Phase 3 tests: Patch generation and verification.

Tests verify:
1. `rewrite_leak_to_try_with_resources` generates valid try-with-resources code.
2. `generate_patch` produces git-apply compatible unified diffs.
3. The rewritten code re-analyzes cleanly with 0 findings in the detector.
4. Git apply --check validates the patch diff format.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from src.parser.ast_loader import parse_file, parse_bytes, find_method_declarations, get_method_name
from src.parser.cfg_builder import build_cfg
from src.analysis.leak_detector import detect_leaks
from src.rules.schema import load_default_java_rules
from src.patch.java_rewriter import rewrite_leak_to_try_with_resources
from src.patch.diff_writer import generate_patch


FIXTURES = Path(__file__).parent / "fixtures" / "java"


class TestPatchGeneration:

    def test_fixture02_patch_generation(self):
        file_path = FIXTURES / "02_leak_missing_close.java"
        tree, source = parse_file(file_path)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        method = methods[0]
        name = get_method_name(method)
        cfg = build_cfg(method)

        findings = detect_leaks(str(file_path), name, cfg, rules, source)
        assert len(findings) == 1
        finding = findings[0]

        # Generate rewritten code
        rewritten = rewrite_leak_to_try_with_resources(source, finding)
        assert rewritten is not None
        assert "try (FileInputStream fis = new FileInputStream(path)) {" in rewritten

        # Generate patch diff
        diff = generate_patch(str(file_path), source, finding)
        assert diff is not None
        assert "--- a/02_leak_missing_close.java" in diff
        assert "+++ b/02_leak_missing_close.java" in diff
        assert "+        try (FileInputStream fis = new FileInputStream(path)) {" in diff

    def test_fixture02_rewritten_code_has_zero_findings(self):
        file_path = FIXTURES / "02_leak_missing_close.java"
        tree, source = parse_file(file_path)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        method = methods[0]
        name = get_method_name(method)
        cfg = build_cfg(method)

        findings = detect_leaks(str(file_path), name, cfg, rules, source)
        assert len(findings) == 1
        finding = findings[0]

        rewritten = rewrite_leak_to_try_with_resources(source, finding)
        rewritten_bytes = rewritten.encode("utf-8")

        # Re-parse and detect leaks on rewritten code
        new_tree = parse_bytes(rewritten_bytes)
        new_methods = find_method_declarations(new_tree)
        new_cfg = build_cfg(new_methods[0])
        new_findings = detect_leaks(str(file_path), name, new_cfg, rules, rewritten_bytes)

        # Confirm zero findings!
        assert len(new_findings) == 0

    def test_fixture04_patch_generation(self):
        file_path = FIXTURES / "04_leak_only_on_exception_path.java"
        tree, source = parse_file(file_path)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        method = methods[0]
        name = get_method_name(method)
        cfg = build_cfg(method)

        findings = detect_leaks(str(file_path), name, cfg, rules, source)
        assert len(findings) == 1
        finding = findings[0]

        rewritten = rewrite_leak_to_try_with_resources(source, finding)
        assert rewritten is not None
        assert "try (FileInputStream fis = new FileInputStream(path)) {" in rewritten
        # Explicit close should be removed in the rewrite
        assert "fis.close();" not in rewritten

        rewritten_bytes = rewritten.encode("utf-8")
        new_tree = parse_bytes(rewritten_bytes)
        new_methods = find_method_declarations(new_tree)
        new_cfg = build_cfg(new_methods[0])
        new_findings = detect_leaks(str(file_path), name, new_cfg, rules, rewritten_bytes)
        assert len(new_findings) == 0

    def test_patch_applies_cleanly_with_git_apply(self):
        file_path = FIXTURES / "02_leak_missing_close.java"
        tree, source = parse_file(file_path)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        finding = detect_leaks(str(file_path), get_method_name(methods[0]), build_cfg(methods[0]), rules, source)[0]

        diff = generate_patch(str(file_path), source, finding)
        assert diff is not None

        # Verify with git apply --check in a temporary repository setup
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            target_file = tmppath / "02_leak_missing_close.java"
            target_file.write_bytes(source)

            diff_file = tmppath / "patch.diff"
            diff_file.write_bytes(diff.encode("utf-8"))

            # Init git repo in tmpdir to test git apply
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "add", "02_leak_missing_close.java"], cwd=tmpdir, check=True, capture_output=True)

            res = subprocess.run(["git", "apply", "--check", "patch.diff"], cwd=tmpdir, capture_output=True, text=True)
            assert res.returncode == 0, f"git apply --check failed: {res.stderr}"
