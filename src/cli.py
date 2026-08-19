"""CLI entrypoint for resource-leak-guard.

Provides the `resource-leak-guard scan` command.
"""

from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

import click

from src.parser.ast_loader import parse_file, find_method_declarations, get_method_name
from src.parser.cfg_builder import build_cfg
from src.analysis.leak_detector import detect_leaks
from src.rules.schema import load_default_java_rules, load_rules
from src.patch.diff_writer import generate_patch
from src.patch.gemini_patcher import generate_llm_patch
from src.analysis.dashboard import generate_html_dashboard
from src.models import Confidence, Finding


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_changed_files(base_ref: str = "HEAD") -> list[Path]:
    """Get list of modified/staged Java files using git diff."""
    try:
        cmd = ["git", "diff", "--name-only", "--cached", base_ref]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        files = res.stdout.splitlines()
        if not files:
            cmd = ["git", "diff", "--name-only", base_ref]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            files = res.stdout.splitlines()
        return [Path(f) for f in files if f.endswith(".java") and Path(f).exists()]
    except Exception:
        return []


def _collect_java_files(path: Path, diff_only: bool) -> list[Path]:
    """Collect .java files to scan."""
    if diff_only:
        return _get_changed_files()

    if path.is_file():
        return [path] if path.suffix == ".java" else []

    return sorted(path.rglob("*.java"))


# ------------------------------------------------------------------
# Main CLI Group
# ------------------------------------------------------------------

@click.group()
@click.version_option(version="0.1.0")
def main():
    """Resource Leak Guard — Static analysis tool for detecting unclosed resources."""
    pass


@main.command(name="scan")
@click.argument("target_path", type=click.Path(exists=True), default=".")
@click.option(
    "--diff-only",
    is_flag=True,
    help="Scan only files changed vs Git base ref.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format (text or json).",
)
@click.option(
    "--fail-on",
    type=click.Choice(["definite", "possible"], case_sensitive=False),
    default="definite",
    help="Minimum confidence level to trigger exit code 1.",
)
@click.option(
    "--rules",
    "rules_path",
    type=click.Path(exists=True),
    default=None,
    help="Custom rules YAML file path.",
)
@click.option(
    "--generate-patches",
    is_flag=True,
    default=True,
    help="Generate unified diff patch suggestions for definite leaks.",
)
@click.option(
    "--use-llm",
    is_flag=True,
    default=False,
    help="Use Gemini API for LLM-assisted fallback patch generation.",
)
@click.option(
    "--html",
    "html_path",
    type=click.Path(),
    default=None,
    help="Export an interactive HTML summary dashboard report.",
)
def scan(
    target_path: str,
    diff_only: bool,
    output_format: str,
    fail_on: str,
    rules_path: Optional[str],
    generate_patches: bool,
    use_llm: bool,
    html_path: Optional[str],
):
    """Scan Java files for unclosed resource leaks."""
    rules = load_rules(rules_path) if rules_path else load_default_java_rules()
    target = Path(target_path)

    files_to_scan = _collect_java_files(target, diff_only)
    if not files_to_scan:
        if output_format == "text":
            click.echo("No Java files found to scan.")
        else:
            click.echo(json.dumps({"findings": [], "summary": {"total": 0}}))
        sys.exit(0)

    all_findings: list[tuple[Finding, str, Optional[str]]] = []

    for file_path in files_to_scan:
        norm_path = str(file_path).replace("\\", "/")
        try:
            tree, source_bytes = parse_file(file_path)
            methods = find_method_declarations(tree)
            for method in methods:
                method_name = get_method_name(method)
                cfg = build_cfg(method)
                method_findings = detect_leaks(
                    norm_path, method_name, cfg, rules, source_bytes
                )
                for f in method_findings:
                    patch = None
                    if generate_patches:
                        if f.confidence == Confidence.DEFINITE:
                            patch = generate_patch(norm_path, source_bytes, f)
                        elif use_llm:
                            patch = generate_llm_patch(norm_path, source_bytes, f)
                    all_findings.append((f, norm_path, patch))
        except Exception as err:
            if output_format == "text":
                click.echo(f"Error scanning {file_path}: {err}", err=True)

    # HTML Dashboard output if requested
    if html_path:
        out_file = generate_html_dashboard(all_findings, html_path)
        if output_format == "text":
            click.secho(f"📊 Dashboard report saved to: {out_file}", fg="cyan", bold=True)

    # Filter findings based on fail-on criteria
    fail_threshold = Confidence.DEFINITE if fail_on == "definite" else Confidence.POSSIBLE

    has_failing_findings = any(
        f.confidence == Confidence.DEFINITE
        or (fail_threshold == Confidence.POSSIBLE and f.confidence == Confidence.POSSIBLE)
        for f, _, _ in all_findings
    )

    if output_format == "text":
        _output_text(all_findings)
    else:
        _output_json(all_findings)

    if has_failing_findings:
        sys.exit(1)
    else:
        sys.exit(0)


def _output_text(all_findings: list[tuple[Finding, str, Optional[str]]]) -> None:
    """Print findings in human-readable terminal format."""
    if not all_findings:
        click.secho("[OK] No resource leaks detected!", fg="green", bold=True)
        return

    click.secho(f"\nResource Leak Guard Findings ({len(all_findings)} found):\n", bold=True)

    for f, file_path, patch in all_findings:
        color = "red" if f.confidence == Confidence.DEFINITE else "yellow"
        click.secho(f"[{f.confidence.name}] {file_path}:{f.line}:{f.column}", fg=color, bold=True)
        click.echo(f"  Method: {f.method_name}")
        click.echo(f"  Resource: {f.resource.type_name} '{f.resource.var_name}'")
        click.echo(f"  Message: {f.message}")

        if patch:
            click.secho("  Suggested Patch:", fg="cyan", bold=True)
            for line in patch.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    click.secho(f"    {line}", fg="green")
                elif line.startswith("-") and not line.startswith("---"):
                    click.secho(f"    {line}", fg="red")
                else:
                    click.echo(f"    {line}")
        click.echo()


def _output_json(all_findings: list[tuple[Finding, str, Optional[str]]]) -> None:
    """Print findings in structured JSON format."""
    items = []
    for f, file_path, patch in all_findings:
        items.append({
            "file": file_path.replace("\\", "/"),
            "line": f.line,
            "column": f.column,
            "method": f.method_name,
            "variable": f.resource.var_name,
            "resource_type": f.resource.type_name,
            "confidence": f.confidence.name,
            "message": f.message,
            "patch": patch,
        })

    output = {
        "findings": items,
        "summary": {
            "total": len(items),
            "definite": sum(1 for f, _, _ in all_findings if f.confidence == Confidence.DEFINITE),
            "possible": sum(1 for f, _, _ in all_findings if f.confidence == Confidence.POSSIBLE),
        }
    }
    click.echo(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
