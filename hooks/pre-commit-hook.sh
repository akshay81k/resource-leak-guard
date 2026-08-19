#!/usr/bin/env bash
# Pre-commit hook for Resource Leak Guard
# Place this script in .git/hooks/pre-commit and make it executable (chmod +x .git/hooks/pre-commit)

set -e

echo "Running Resource Leak Guard pre-commit check..."

# Run scan on staged files only
if command -v resource-leak-guard &> /dev/null; then
    CLI_CMD="resource-leak-guard"
else
    CLI_CMD="python -m src.cli"
fi

$CLI_CMD scan --diff-only --fail-on=definite

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ Pre-commit check failed: Unclosed resource leak(s) detected!"
    echo "Please fix the leaks or apply the suggested try-with-resources patch."
    exit 1
fi

echo "✔ Resource Leak Guard pre-commit check passed."
exit 0
