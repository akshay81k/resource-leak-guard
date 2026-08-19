"""HTML Dashboard & Summary Report Generator for Resource Leak Guard findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from src.models import Finding


def generate_html_dashboard(
    findings_with_patches: Sequence[tuple[Finding, str, str | None]],
    output_path: str = "resource-leak-report.html",
) -> str:
    """Generate a sleek, standalone HTML report for scan findings."""
    total = len(findings_with_patches)
    definite = sum(1 for f, _, _ in findings_with_patches if f.confidence == f.confidence.DEFINITE)
    possible = sum(1 for f, _, _ in findings_with_patches if f.confidence == f.confidence.POSSIBLE)

    cards_html = []
    for f, file_path, patch in findings_with_patches:
        conf_class = "badge-definite" if f.confidence == f.confidence.DEFINITE else "badge-possible"
        patch_html = ""
        if patch:
            escaped_patch = patch.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            patch_html = f"""
            <div class="patch-container">
                <div class="patch-title">Suggested Patch</div>
                <pre class="patch-code"><code>{escaped_patch}</code></pre>
            </div>
            """

        cards_html.append(f"""
        <div class="card {f.confidence.name.lower()}">
            <div class="card-header">
                <span class="badge {conf_class}">{f.confidence.name}</span>
                <span class="file-info">{file_path}:{f.line}:{f.column}</span>
            </div>
            <div class="card-body">
                <div class="detail-row"><strong>Method:</strong> <code>{f.method_name}</code></div>
                <div class="detail-row"><strong>Resource:</strong> <code>{f.resource.type_name} '{f.resource.var_name}'</code></div>
                <div class="detail-row"><strong>Message:</strong> {f.message}</div>
                {patch_html}
            </div>
        </div>
        """)

    cards_str = "\n".join(cards_html) if cards_html else "<div class='no-findings'>✔ No resource leaks detected in codebase!</div>"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resource Leak Guard — Summary Dashboard</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text: #f8fafc;
            --text-muted: #94a3b8;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-green: #10b981;
            --border: #334155;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 2rem;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }}
        h1 {{ margin: 0; font-size: 1.8rem; font-weight: 700; }}
        .metrics {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .metric-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 0.5rem;
            padding: 1.25rem;
            text-align: center;
        }}
        .metric-value {{ font-size: 2rem; font-weight: 800; margin-top: 0.25rem; }}
        .text-red {{ color: var(--accent-red); }}
        .text-yellow {{ color: var(--accent-yellow); }}
        .text-green {{ color: var(--accent-green); }}

        .findings-list {{ display: flex; flex-direction: column; gap: 1rem; }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 0.5rem;
            padding: 1.25rem;
        }}
        .card-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 0.75rem;
        }}
        .badge {{
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-definite {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); border: 1px solid var(--accent-red); }}
        .badge-possible {{ background: rgba(245, 158, 11, 0.2); color: var(--accent-yellow); border: 1px solid var(--accent-yellow); }}
        .file-info {{ font-family: monospace; color: var(--text-muted); font-size: 0.9rem; }}
        .detail-row {{ margin-bottom: 0.4rem; font-size: 0.95rem; }}
        code {{ background: #0f172a; padding: 0.2rem 0.4rem; border-radius: 0.25rem; font-family: monospace; color: #38bdf8; }}
        
        .patch-container {{
            margin-top: 1rem;
            background: #090d16;
            border: 1px solid var(--border);
            border-radius: 0.375rem;
            overflow: hidden;
        }}
        .patch-title {{
            background: #1e293b;
            padding: 0.4rem 0.8rem;
            font-size: 0.8rem;
            font-weight: 600;
            color: #94a3b8;
            border-bottom: 1px solid var(--border);
        }}
        .patch-code {{ margin: 0; padding: 0.8rem; font-family: monospace; font-size: 0.85rem; overflow-x: auto; color: #e2e8f0; }}
        .no-findings {{ text-align: center; padding: 3rem; background: var(--card-bg); border-radius: 0.5rem; color: var(--accent-green); font-size: 1.2rem; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Resource Leak Guard Report</h1>
        <div style="color: var(--text-muted); font-size: 0.9rem;">Static Analysis Report</div>
    </div>

    <div class="metrics">
        <div class="metric-card">
            <div>Total Findings</div>
            <div class="metric-value">{total}</div>
        </div>
        <div class="metric-card">
            <div>Definite Leaks</div>
            <div class="metric-value text-red">{definite}</div>
        </div>
        <div class="metric-card">
            <div>Possible Leaks</div>
            <div class="metric-value text-yellow">{possible}</div>
        </div>
    </div>

    <h2>Findings Detail</h2>
    <div class="findings-list">
        {cards_str}
    </div>
</body>
</html>
"""

    p = Path(output_path)
    p.write_text(html_content, encoding="utf-8")
    return str(p.absolute())
