#!/bin/bash
set -euo pipefail
echo "=== Running Aegis Tests ==="

echo "--- Python unit tests ---"
python -m pytest tests/unit/ -v --tb=short

echo "--- Go tests ---"
cd scheduler/aegis-scheduler && go test ./... -v && cd ../..

echo "=== All tests passed ==="
