#!/usr/bin/env python3
"""
Download and extract Azure Functions 2019 trace data.

Source:
  Azure Public Dataset (USENIX ATC'20 "Serverless in the Wild", CC-BY)
  https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz

Usage:
  python scripts/download_azure_traces.py [--verify-only] [--extract] [--download-dir datasets/raw]

Note: Raw CSV and tar.xz data are ignored by git (.gitignore) and must NOT be committed.
"""

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import urllib.request

TAR_URL = "https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz"
TAR_NAME = "azurefunctions_dataset2019.tar.xz"
CHECKSUMS_FILE = os.path.join("datasets", "CHECKSUMS.txt")


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def load_checksums() -> dict:
    if not os.path.exists(CHECKSUMS_FILE):
        return {}
    checksums = {}
    with open(CHECKSUMS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                checksums[parts[1].replace("\\", "/")] = parts[0].lower()
    return checksums


def verify_checksums(base_dir: str = ".") -> bool:
    expected = load_checksums()
    if not expected:
        print(f"[!] Warning: No checksums file found at {CHECKSUMS_FILE}")
        return False

    all_ok = True
    print(f"[*] Verifying SHA-256 checksums from {CHECKSUMS_FILE}...")
    for rel_path, exp_hash in expected.items():
        full_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(full_path):
            print(f"  [MISSING] {rel_path}")
            all_ok = False
            continue
        calc_hash = compute_sha256(full_path)
        if calc_hash.lower() == exp_hash.lower():
            print(f"  [OK]      {rel_path}")
        else:
            print(f"  [MISMATCH] {rel_path} (got {calc_hash[:12]}..., expected {exp_hash[:12]}...)")
            all_ok = False
    return all_ok


def download_tar(target_path: str):
    print(f"[*] Downloading {TAR_URL} to {target_path}...")
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    def report_hook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = downloaded / total_size * 100
            mb_down = downloaded / (1024 * 1024)
            mb_tot = total_size / (1024 * 1024)
            sys.stdout.write(f"\r    {mb_down:.1f} MB / {mb_tot:.1f} MB ({percent:.1f}%)")
        else:
            sys.stdout.write(f"\r    {downloaded / (1024 * 1024):.1f} MB downloaded")
        sys.stdout.flush()

    urllib.request.urlretrieve(TAR_URL, target_path, reporthook=report_hook)
    print("\n[*] Download complete.")


def extract_tar(tar_path: str, extract_dir: str):
    print(f"[*] Extracting {tar_path} into {extract_dir}...")
    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(tar_path, "r:xz") as tar:
        tar.extractall(path=extract_dir)
    print("[*] Extraction complete.")


def main():
    parser = argparse.ArgumentParser(description="Download and verify Azure Functions 2019 dataset.")
    parser.add_argument("--download-dir", default=os.path.join("datasets", "raw"), help="Directory for raw files")
    parser.add_argument("--verify-only", action="store_true", help="Only verify checksums against CHECKSUMS.txt")
    parser.add_argument("--skip-extract", action="store_true", help="Do not extract the archive after download")
    args = parser.parse_args()

    if args.verify_only:
        ok = verify_checksums()
        sys.exit(0 if ok else 1)

    tar_path = os.path.join(args.download_dir, TAR_NAME)
    extract_target = os.path.join(args.download_dir, "azurefunctions2019")

    if not os.path.exists(tar_path):
        download_tar(tar_path)
    else:
        print(f"[*] Archive already exists at {tar_path}.")

    if not args.skip_extract:
        if not os.path.exists(extract_target) or not os.listdir(extract_target):
            extract_tar(tar_path, extract_target)
        else:
            print(f"[*] Extracted files already present in {extract_target}.")

    verify_checksums()

    print("\n[+] To regenerate parquet caches:")
    print("    1. python datasets/load_real_trace.py")
    print("    2. python eval/run_60app_study.py")


if __name__ == "__main__":
    main()
