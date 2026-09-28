#!/bin/bash
set -euo pipefail
# Load generator wrapper for Aegis evaluation
TARGET_URL=${TARGET_URL:-"localhost:8080"}
SCENARIO=${1:-"burst-test"}

echo "Running load scenario: $SCENARIO against $TARGET_URL"

if command -v k6 >/dev/null 2>&1; then
    k6 run --env TARGET_URL=$TARGET_URL tests/load/scenarios/${SCENARIO}.js
elif command -v hey >/dev/null 2>&1; then
    echo "Falling back to hey (basic burst test)"
    hey -z 5m -c 50 -q 100 http://$TARGET_URL/
else
    echo "Error: neither k6 nor hey found. Install one of them."
    exit 1
fi
