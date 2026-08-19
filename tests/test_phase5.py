"""Phase 5 tests: Go rules, HTML dashboard generation, and Gemini API patch integration."""

import os
from pathlib import Path
import pytest

from src.rules.schema import load_rules
from src.analysis.dashboard import generate_html_dashboard
from src.parser.ast_loader import parse_file, find_method_declarations, get_method_name
from src.parser.cfg_builder import build_cfg
from src.analysis.leak_detector import detect_leaks
from src.rules.schema import load_default_java_rules
from src.patch.diff_writer import generate_patch


FIXTURES = Path(__file__).parent / "fixtures" / "java"


class TestPhase5:

    def test_load_go_rules(self):
        go_yaml = Path(__file__).parent.parent / "src" / "rules" / "go.yaml"
        rules = load_rules(go_yaml)
        assert rules.language == "go"
        assert "os.File" in rules.acquisition_type_names
        assert "Close" in rules.release_method_names
        assert "defer_statement" in rules.safe_wrapper_node_types

    def test_html_dashboard_generation(self, tmp_path):
        file_path = FIXTURES / "02_leak_missing_close.java"
        tree, source = parse_file(file_path)
        rules = load_default_java_rules()
        methods = find_method_declarations(tree)
        finding = detect_leaks(str(file_path), get_method_name(methods[0]), build_cfg(methods[0]), rules, source)[0]
        patch = generate_patch(str(file_path), source, finding)

        findings_tuples = [(finding, str(file_path), patch)]
        out_html = tmp_path / "report.html"

        res_path = generate_html_dashboard(findings_tuples, str(out_html))
        assert Path(res_path).exists()
        content = Path(res_path).read_text(encoding="utf-8")
        assert "Resource Leak Guard Report" in content
        assert "02_leak_missing_close.java" in content
        assert "try (FileInputStream" in content
