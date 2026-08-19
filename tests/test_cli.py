"""Phase 4 tests: CLI commands and integration.

Tests verify:
1. CLI text output format and non-zero exit codes on leaks.
2. CLI JSON output structure.
3. --fail-on option (definite vs possible).
4. Scanning clean files returns exit code 0.
"""

from pathlib import Path

from click.testing import CliRunner

from src.cli import main


FIXTURES = Path(__file__).parent / "fixtures" / "java"


class TestCLI:

    def test_cli_scan_leaky_fixture_fails(self):
        runner = CliRunner()
        leaky_file = FIXTURES / "02_leak_missing_close.java"
        result = runner.invoke(main, ["scan", str(leaky_file)])

        assert result.exit_code == 1
        assert "Resource Leak Guard Findings" in result.output
        assert "DEFINITE" in result.output
        assert "fis" in result.output
        assert "Suggested Patch:" in result.output

    def test_cli_scan_safe_fixture_passes(self):
        runner = CliRunner()
        safe_file = FIXTURES / "01_no_leak_explicit_close.java"
        result = runner.invoke(main, ["scan", str(safe_file)])

        assert result.exit_code == 0
        assert "No resource leaks detected" in result.output

    def test_cli_json_output_format(self):
        runner = CliRunner()
        leaky_file = FIXTURES / "02_leak_missing_close.java"
        result = runner.invoke(main, ["scan", str(leaky_file), "--format=json"])

        assert result.exit_code == 1
        assert '"findings":' in result.output
        assert '"confidence": "DEFINITE"' in result.output
        assert '"patch":' in result.output

    def test_cli_fail_on_possible_option(self):
        runner = CliRunner()
        possible_file = FIXTURES / "07_possible_leak_passed_to_helper.java"

        # Default fail-on=definite should exit 0 for POSSIBLE finding
        res_default = runner.invoke(main, ["scan", str(possible_file), "--fail-on=definite"])
        assert res_default.exit_code == 0

        # fail-on=possible should exit 1
        res_possible = runner.invoke(main, ["scan", str(possible_file), "--fail-on=possible"])
        assert res_possible.exit_code == 1

    def test_cli_scan_directory(self):
        runner = CliRunner()
        result = runner.invoke(main, ["scan", str(FIXTURES)])
        assert result.exit_code == 1
        assert "Resource Leak Guard Findings" in result.output
