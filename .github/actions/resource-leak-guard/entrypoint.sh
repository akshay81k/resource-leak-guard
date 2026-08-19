#!/usr/bin/env bash
# GitHub Action Entrypoint for Resource Leak Guard

TARGET_PATH="${1:-.}"
FAIL_ON="${2:-definite}"
DIFF_ONLY="${3:-false}"

EXTRA_FLAGS=""
if [ "$DIFF_ONLY" = "true" ]; then
    EXTRA_FLAGS="--diff-only"
fi

CLI_CMD="python -m src.cli"

# Run scan in JSON format to capture structured findings
JSON_OUTPUT=$($CLI_CMD scan "$TARGET_PATH" --format=json --fail-on="$FAIL_ON" $EXTRA_FLAGS 2>/dev/null || true)

# Run in human text format for GitHub runner logs
$CLI_CMD scan "$TARGET_PATH" --format=text --fail-on="$FAIL_ON" $EXTRA_FLAGS || SCAN_EXIT=$?

TOTAL_FINDINGS=$(echo "$JSON_OUTPUT" | python -c "import sys, json; 
try:
    data = json.load(sys.stdin)
    print(data.get('summary', {}).get('total', 0))
except Exception:
    print(0)
")

DEFINITE_FINDINGS=$(echo "$JSON_OUTPUT" | python -c "import sys, json; 
try:
    data = json.load(sys.stdin)
    print(data.get('summary', {}).get('definite', 0))
except Exception:
    print(0)
")

if [ -n "$GITHUB_OUTPUT" ]; then
    echo "findings_count=$TOTAL_FINDINGS" >> "$GITHUB_OUTPUT"
fi

# Format GitHub Workflow Annotations
echo "$JSON_OUTPUT" | python -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for finding in data.get('findings', []):
        level = 'error' if finding['confidence'] == 'DEFINITE' else 'warning'
        file = finding['file']
        line = finding['line']
        col = finding['column']
        msg = finding['message']
        print(f'::{level} file={file},line={line},col={col}::{msg}')
except Exception:
    pass
"

if [ "$FAIL_ON" = "definite" ] && [ "$DEFINITE_FINDINGS" -gt 0 ]; then
    echo "❌ Build failed due to $DEFINITE_FINDINGS definite resource leak(s)."
    exit 1
elif [ "$FAIL_ON" = "possible" ] && [ "$TOTAL_FINDINGS" -gt 0 ]; then
    echo "❌ Build failed due to $TOTAL_FINDINGS leak finding(s)."
    exit 1
elif [ "${SCAN_EXIT:-0}" -ne 0 ]; then
    echo "❌ Build failed: Scanner returned exit code ${SCAN_EXIT}."
    exit 1
fi

echo "✔ Resource Leak Guard check completed successfully."
exit 0
