# Resource Leak Guard 🛡️

> Static analysis CLI tool & GitHub Action that statically analyzes source code to detect unclosed resources (file handles, database connections, sockets, streams), fails CI builds when found, and auto-generates `try-with-resources` patch suggestions.

---

## 📸 GitHub Actions CI/CD Flow in Action

### 1. Resource Leak Detected in CI (Red X ❌)
When unclosed resources (such as `Connection`, `Statement`, `ResultSet`, `FileWriter`, or `FileInputStream`) are committed, the GitHub Action automatically detects them, adds GitHub Workflow error annotations, and fails the CI build.

![Resource Leaks Detected in CI](imgs/Screenshot%202026-08-20%20002104.png)

---

### 2. Auto-Generated `try-with-resources` Patch Suggestions
The scanner generates clean, git-apply compatible unified diff patches in the runner logs and PR comments:

![Auto Generated Patch Suggestion](imgs/Screenshot%202026-08-20%20002238.png)

```text
Error: 'Connection' opened as 'conn' is never closed
Error: 'Statement' opened as 'stmt' is never closed
Error: 'ResultSet' opened as 'rs' is never closed
Error: 'FileWriter' opened as 'writer' is never closed
❌ Build failed due to 4 definite resource leak(s).
```

![Build Failed Log Summary](imgs/Screenshot%202026-08-20%20002255.png)

---

### 3. Build Passes After Applying Fix (Green Check ✔️)
Once resources are properly managed using `try-with-resources` (or `defer` in Go), re-scanning produces 0 findings and the CI workflow turns green!

![CI Build Success](imgs/Screenshot%202026-08-20%20002313.png)

---

## ✨ Features

- 🔍 **Static AST & Control-Flow Analysis**: Parses Java & Go code using `tree-sitter`, constructs per-method Control-Flow Graphs (CFG), and executes forward dataflow analysis.
- ⚡ **Exception-Path Leak Detection**: Identifies resources closed on normal execution paths but leaked if an exception is thrown before `.close()`.
- 🛠️ **Automated Patch Generation**: Generates valid `try-with-resources` block unified diffs that apply cleanly via `git apply`.
- 🤖 **Gemini AI LLM Fallback**: Integrates Google Gemini API (`gemini-2.5-flash`) to generate AI-assisted patch suggestions for complex or conditional leaks.
- 📊 **Interactive HTML Dashboard**: Generates standalone HTML report dashboards with metrics, findings details, and diff previews.
- 🚀 **CI/CD Integration**: Shipped as a GitHub Action (`action.yml`) and Git `pre-commit` hook.

---

## 🚀 Quick Start

### Installation

```bash
# 1. Clone repository
git clone https://github.com/akshay81k/resource-leak-guard.git
cd resource-leak-guard

# 2. Create virtual environment
python -m venv venv

# 3. Activate venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
# source venv/bin/activate

# 4. Install dependencies and CLI package
pip install -r requirements.txt
pip install -e .
```

---

## 💻 CLI Commands & Usage Reference

```bash
# Scan current directory recursively
resource-leak-guard scan

# Scan a specific directory or file
resource-leak-guard scan src/main/java

# Scan only files modified in git diff
resource-leak-guard scan --diff-only

# Output structured JSON format for CI pipelines
resource-leak-guard scan --format=json

# Generate an interactive HTML Dashboard Report
resource-leak-guard scan --html=resource-leak-report.html

# Enable Google Gemini AI fallback for complex leak patching
resource-leak-guard scan --use-llm

# Fail build on POSSIBLE leaks as well as DEFINITE leaks
resource-leak-guard scan --fail-on=possible

# Use custom YAML rules
resource-leak-guard scan --rules=src/rules/java.yaml
```

---

## 📊 Summary HTML Dashboard

Generate an HTML dashboard report for your project with a single flag:

```bash
resource-leak-guard scan --html=report.html
```

The generated `report.html` includes:
- **Total Findings Counter** (Definite vs Possible)
- **File, Line & Method Breakdown**
- **Syntax-Highlighted Patch Previews**

---

## ⚙️ Configuration (`.env`)

For Gemini AI LLM-assisted fallback patching, create a `.env` file in your root folder:

```env
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_PROJECT_ID=422565868377
```

---

## 📋 Rule-Based Architecture (Extensible to New Languages)

Rules are defined in simple YAML files (`src/rules/java.yaml`, `src/rules/go.yaml`) specifying:
- **Acquisitions**: Closeable types (`FileInputStream`, `Connection`, `Socket`, etc.) and factory methods (`DriverManager.getConnection`).
- **Releases**: Method names that release the resource (`close`, `Close`, `disconnect`).
- **Safe Wrappers**: AST constructs (`try_with_resources_statement`, `defer_statement`).

See [`docs/rule-file-format.md`](docs/rule-file-format.md) for details on adding new language rules.

---

## ⚓ Local Pre-Commit Hook Setup

Prevent committing unclosed resource leaks locally:

```bash
cp hooks/pre-commit-hook.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

---

## 🐙 GitHub Action CI Setup

Add `.github/workflows/self_check.yml` to your repository:

```yaml
name: Resource Leak Guard CI

on:
  push:
    branches: [ main, master ]
  pull_request:
    branches: [ main, master ]

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Resource Leak Guard
        uses: ./.github/actions/resource-leak-guard
        with:
          path: "src/main/java"
          fail-on: "definite"
```

---

## 🧪 Testing

Run the test suite (50 unit & integration tests):

```bash
pytest -v
```
