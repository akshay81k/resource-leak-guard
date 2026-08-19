#!/usr/bin/env bash
# GitHub Action Entrypoint for Resource Leak Guard

TARGET_PATH="${1:-.}"
FAIL_ON="${2:-definite}"
DIFF_ONLY="${3:-false}"

EXTRA_FLAGS=""
if [ "$DIFF_ONLY" = "true" ]; then
    EXTRA_FLAGS="--diff-only"
fi

# Run scan in JSON format
JSON_OUTPUT=$(resource-leak-guard scan "$TARGET_PATH" --format=json --fail-on="$FAIL_ON" $EXTRA_FLAGS || true)

# Also run in human text format for logs
resource-leak-guard scan "$TARGET_PATH" --format=text --fail-on="$FAIL_ON" $EXTRA_FLAGS || EXIT_CODE=$?

TOTAL_FINDINGS=$(echo "$JSON_OUTPUT" | python -c "import sys, json; data=json.load(sys.stdin); print(data.get('summary', {}).get('total', 0))")
DEFINITE_FINDINGS=$(echo "$JSON_OUTPUT" | python -c "import sys, json; data=json.load(sys.stdin); print(data.get('summary', {}).get('definite', 0))")

echo "findings_count=$TOTAL_FINDINGS" >> "$GITHUB_OUTPUT"

# Format GitHub Workflow Annotations
echo "$JSON_OUTPUT" | python -c "
import sys, json

data = json.load(sys.stdin)
for finding in data.get('findings', []):
    level = 'error' if finding['confidence'] == 'DEFINITE' else 'warning'
    file = finding['file']
    line = finding['line']
    col = finding['column']
    msg = finding['message']
    print(f'::{level} file={file},line={line},col={col}::{msg}')
"

if [ "$FAIL_ON" = "definite" ] && [ "$DEFINITE_FINDINGS" -gt 0 ]; then
    echo "❌ Build failed due to $DEFINITE_FINDINGS definite resource leak(s)."
    exit 1
elif [ "$FAIL_ON" = "possible" ] && [ "$TOTAL_FINDINGS" -gt 0 ]; then
    echo "❌ Build failed due to $TOTAL_FINDINGS leak finding(s)."
    exit 1
fi

echo "✔ Resource Leak Guard check completed successfully."
exit 0
