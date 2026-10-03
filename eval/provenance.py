"""
Provenance tracking helper for Aegis evaluation scripts.
Emits standard experiment provenance metadata:
{
    'git_commit': str,
    'dirty_flag': bool,
    'config_sha256': str,
    'timestamp_utc': str,
    'seeds': List[int]
}
"""

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def get_git_commit(cwd: Optional[str] = None) -> str:
    """Returns current git commit hash (HEAD) or 'unknown' on failure."""
    try:
        root_dir = cwd or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=root_dir,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_git_dirty_flag(cwd: Optional[str] = None) -> bool:
    """Returns True if uncommitted working-tree changes exist, False otherwise."""
    try:
        root_dir = cwd or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=root_dir,
        )
        if res.returncode == 0:
            return bool(res.stdout.strip())
    except Exception:
        pass
    return False


def compute_config_hash(cfg: Any) -> str:
    """
    Computes deterministic SHA-256 hash of configuration dictionary.
    Keys are sorted to ensure reproducibility across runs and environments.
    """
    if cfg is None:
        cfg = {}
    raw = json.dumps(cfg, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_provenance(
    config: Optional[Dict[str, Any]] = None,
    seeds: Optional[List[int]] = None,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Emits standard provenance dictionary:
    {
        'git_commit': str,
        'dirty_flag': bool,
        'config_sha256': str,
        'timestamp_utc': str,
        'seeds': List[int]
    }
    """
    return {
        "git_commit": get_git_commit(cwd),
        "dirty_flag": get_git_dirty_flag(cwd),
        "config_sha256": compute_config_hash(config),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": list(seeds) if seeds is not None else [42],
    }
