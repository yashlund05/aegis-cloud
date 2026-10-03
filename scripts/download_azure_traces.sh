#!/usr/bin/env bash
# Download and extract Azure Functions 2019 dataset
set -euo pipefail

TAR_URL="https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz"
RAW_DIR="datasets/raw"
TAR_FILE="${RAW_DIR}/azurefunctions_dataset2019.tar.xz"
EXTRACT_DIR="${RAW_DIR}/azurefunctions2019"

mkdir -p "${RAW_DIR}"

if [ ! -f "${TAR_FILE}" ]; then
    echo "[*] Downloading Azure Functions 2019 dataset..."
    curl -L "${TAR_URL}" -o "${TAR_FILE}"
else
    echo "[*] Archive ${TAR_FILE} already exists."
fi

mkdir -p "${EXTRACT_DIR}"
if [ -z "$(ls -A "${EXTRACT_DIR}" 2>/dev/null)" ]; then
    echo "[*] Extracting ${TAR_FILE} to ${EXTRACT_DIR}..."
    tar -xf "${TAR_FILE}" -C "${EXTRACT_DIR}"
else
    echo "[*] Extracted files already present in ${EXTRACT_DIR}."
fi

echo "[*] Verifying checksums with Python helper..."
python scripts/download_azure_traces.py --verify-only

echo "[+] To regenerate parquet caches:"
echo "    python datasets/load_real_trace.py"
echo "    python eval/run_60app_study.py"
