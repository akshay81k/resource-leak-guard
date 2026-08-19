# Resource Leak Guard 🛡️

> Static analysis tool & CI/CD Action that detects unclosed resource leaks (file handles, sockets, DB connections) in source code and auto-generates `try-with-resources` patch suggestions.

---

## Features

- 🔍 **Static AST & Control-Flow Analysis**: Parses Java source code using `tree-sitter`, builds per-method CFGs, and performs forward dataflow analysis.
- ⚡ **Exception-Path Leak Detection**: Flags resources closed on happy paths but leaked when an exception is thrown before `.close()`.
- 🛠️ **Automated Patch Generation**: AST rewriter automatically generates `try-with-resources` block unified diffs ready to apply via `git apply`.
- 🤖 **Gemini AI Fallback Patching**: Integrates Google Gemini API (`gemini-2.5-flash`) for intelligent patch suggestions on complex findings.
- 📊 **HTML Dashboard Reports**: Generates standalone, interactive HTML report dashboards with metrics and diff previews.
- 🚀 **CI/CD Integration**: Includes a GitHub Action (`action.yml`) and Git `pre-commit` hook.

---

## Quick Start

### Installation

```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate # Linux/macOS

pip install -r requirements.txt
pip install -e .
```

### CLI Usage

```bash
# Scan entire project
resource-leak-guard scan

# Scan specific file or directory
resource-leak-guard scan src/main/java

# Scan changed files in Git PR diff only
resource-leak-guard scan --diff-only

# Generate JSON report for CI pipelines
resource-leak-guard scan --format=json

# Generate HTML Summary Dashboard Report
resource-leak-guard scan --html=leak-report.html

# Enable Gemini AI LLM fallback patching
resource-leak-guard scan --use-llm
```

---

## Configuration (`.env`)

For Gemini AI LLM-assisted fallback patching, set your API key in `.env`:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_PROJECT_ID=422565868377
```

---

## Rule Configuration & Adding Languages

Rule files (`src/rules/java.yaml`, `src/rules/go.yaml`) configure closeable types, release methods, and safe wrappers. See [`docs/rule-file-format.md`](docs/rule-file-format.md) for details on adding new language rules.

---

## Pre-Commit Hook Setup

```bash
cp hooks/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

---

## GitHub Action Setup

Add to `.github/workflows/self_check.yml`:

```yaml
uses: ./.github/actions/resource-leak-guard
with:
  path: "."
  fail-on: "definite"
```
