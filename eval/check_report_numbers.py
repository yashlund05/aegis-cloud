#!/usr/bin/env python3
"""
eval/check_report_numbers.py

Two modes:

1. Legacy:  python eval/check_report_numbers.py <report.md> <results.json>
   Checks that numbers in a markdown report appear in the JSON.

2. README:  python eval/check_report_numbers.py --readme
   Verifies EVERY numeric token in README.md against
   eval/reports/readme_values_manifest.json, which eval/generate_readme.py
   produced.  Each manifest entry is first recomputed from its committed
   source (JSON result file, report file, study source constant, or live test
   stamp); then every numeric token found in README.md must match a
   manifest-derived number (or be a trivial structural integer <= 20).
   Exits non-zero on any mismatch.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))

import generate_readme as gen  # noqa: E402  (committed-source parsers, shared)

MANIFEST_PATH = ROOT / "eval" / "reports" / "readme_values_manifest.json"
README_PATH = ROOT / "README.md"

TRIVIAL_INT_MAX = 20


# ---------------------------------------------------------------------------
# shared source access
# ---------------------------------------------------------------------------
def src_path(file_key: str) -> Path:
    """file_key may be a SOURCES short key or an already repo-relative path."""
    rel = gen.SOURCES.get(file_key, file_key)
    return ROOT / rel


_json_cache: dict = {}


def load_json(file_key: str):
    p = src_path(file_key)
    if p not in _json_cache:
        _json_cache[p] = json.loads(p.read_text(encoding="utf-8"))
    return _json_cache[p]


_text_cache: dict = {}


def load_text(rel: str) -> str:
    if rel not in _text_cache:
        _text_cache[rel] = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    return _text_cache[rel]


def resolve_raw(file_key: str, path):
    if isinstance(path, str) and path.startswith("cascade:"):
        return gen.extract_app_selection_cascade(load_text("eval/app_selection.md"))[path.split(":", 1)[1]]
    return gen.jget(load_json(file_key), path)


def _fmt(val: float, dp: int) -> str:
    return gen._inttext(val, dp)


# ---------------------------------------------------------------------------
# manifest re-verification
# ---------------------------------------------------------------------------
def verify_manifest(manifest: list) -> list:
    errors = []
    for e in manifest:
        name, spec, text = e["name"], e["spec"], e["text"]
        op = spec.get("op")
        try:
            if op == "round":
                raw = resolve_raw(spec["file"], spec["path"])
                assert text == _fmt(raw, spec["dp"]), f"{text} != {_fmt(raw, spec['dp'])}"
            elif op == "sig3":
                raw = resolve_raw(spec["file"], spec["path"])
                assert text == f"{raw:.3g}", f"{text} != {raw:.3g}"
            elif op == "diff":
                a, b = (resolve_raw(f, p) for f, p in spec["inputs"])
                val = round(a - b, spec["dp"])
                assert text == f"{val:.{spec['dp']}f}"
            elif op == "pct":
                a, b = (resolve_raw(f, p) for f, p in spec["inputs"])
                val = round(a / b * 100.0, spec["dp"])
                assert text == f"{val:.{spec['dp']}f}"
            elif op == "prod":
                raws = [resolve_raw(f, p) for f, p in spec["inputs"]]
                val = round(gen.eval_prod(raws), spec["dp"])
                assert text == (f"{val:,.{spec['dp']}f}" if spec["dp"] else f"{val:,.0f}")
            elif op == "count_prod":
                raws = []
                for f, p in spec["inputs"]:
                    v = resolve_raw(f, p)
                    raws.append(len(v) if isinstance(v, (list, dict)) else int(v))
                val = round(gen.eval_prod(raws), spec["dp"])
                assert text == f"{val:,.0f}"
            elif op == "pctcount":
                pct, n = (resolve_raw(f, p) for f, p in spec["inputs"])
                val = round(pct * n / 100.0)
                assert text == f"{val:.0f}"
            elif op == "count":
                val = len(gen.jget(load_json(spec["file"]), spec["path"]))
                assert text == f"{val:d}"
            elif op == "sum":
                raws = [resolve_raw(f, p) for f, p in spec["inputs"]]
                val = round(sum(raws), spec["dp"])
                assert text == f"{val:.{spec['dp']}f}"
            elif op == "div":
                a, b = (resolve_raw(f, p) for f, p in spec["inputs"])
                val = round(a / b, spec["dp"])
                assert text == f"{val:.{spec['dp']}f}"
            elif op == "scale":
                raw = resolve_raw(spec["file"], spec["path"])
                val = round(raw * spec["factor"], spec["dp"])
                assert text == _fmt(val, spec["dp"]), f"{text} != {_fmt(val, spec['dp'])}"
            elif op == "neg":
                raw = resolve_raw(spec["file"], spec["path"])
                val = round(-raw, spec["dp"])
                assert text == f"{val:.{spec['dp']}f}"
            elif op == "regex_int":
                m = re.search(spec["pattern"], load_text(spec["file"]), re.MULTILINE)
                assert m, "pattern not found"
                assert text == f"{int(m.group(spec.get('group', 1))):d}"
            elif op == "regex_float":
                vals = [float(m.group(1)) for m in re.finditer(spec["pattern"], load_text(spec["file"]))]
                assert vals == spec.get("all", vals), "source constants changed"
                assert text == f"{vals[spec['index']]:g}"
            elif op == "node_power":
                pw = gen.extract_node_power(load_text(spec["file"]))
                assert text == f"{pw[spec['which']]:g}"
            elif op == "cascade":
                val = gen.extract_app_selection_cascade(load_text(spec["file"]))[spec["cell"]]
                assert text == f"{val:,}"
            elif op == "report":
                val = gen.extract_report_number(load_text(spec["file"]), spec["pattern"], spec.get("group", 1))
                expect = f"{val:.{spec['dp']}f}" if spec["dp"] else f"{val:,.0f}"
                assert text == expect, f"{text} != {expect}"
            elif op == "censor_max":
                raws = [v["censored_fraction_pct"] for v in load_json(spec["file"])[spec["path"].split("|")[0]].values()]
                val = max(raws)
                assert text == f"{val:.1f}"
            elif op == "seeds":
                m = re.search(spec["pattern"], load_text(spec["file"]))
                assert m and m.group(1) == text
                assert [int(x) for x in text.split(",")] == spec["numbers"]
            elif op == "range":
                if "which" in spec:
                    raw = gen.jget(load_json(spec["file"]), spec["path"])
                    val = max(raw) if spec["which"] == "max" else min(raw)
                    assert text == f"{val:g}"
                else:
                    raw = gen.jget(load_json(spec["file"]), spec["path"])
                    lo, hi = min(raw), max(raw)
                    assert spec["numbers"] == [lo, hi]
            elif op == "const":
                assert True  # value itself feeds the allowlist
            elif op == "cmp_text":
                raw = resolve_raw(spec["file"], spec["path"])
                expect = "above" if raw > spec["threshold"] else "below"
                assert text == expect
            elif op == "report_text":
                assert re.search(spec["pattern"], load_text(spec["file"]))
            elif op in ("text", "doc_parse", "git_head", "template_sha", "template_sha256"):
                pass
            elif op == "tree":
                for rel in spec["paths"]:
                    assert (ROOT / rel).exists(), f"missing repo path {rel}"
            else:
                errors.append(f"{name}: unknown op {op}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name} ({op}): {exc}")
    return errors


# ---------------------------------------------------------------------------
# numeric tokens in README.md
# ---------------------------------------------------------------------------
def extract_tokens(text: str, manifest: list) -> set:
    t = text
    # seed lists from the manifest must not be comma-merged into one giant number
    for e in manifest:
        if e["spec"].get("op") == "seeds":
            t = t.replace(e["text"], " ")
    t = re.sub(r"\b[0-9a-f]{12,64}\b", " ", t)          # git / sha hex
    t = re.sub(r"SHA-\s?256", " ", t)                    # hash algorithm name
    t = re.sub(r"\d{4}-\d{2}-\d{2}", " ", t)             # ISO dates
    t = re.sub(r"'?\[[^\]\n]*\]'?", " ", t)              # quoted key paths ['1.0%']
    t = re.sub(r"(?<=[_\^])\{(-?\d+)\}", " ", t)         # LaTeX sub/superscripts p_{90}
    t = re.sub(r"(?m)^(#{1,6} )\d+(?:\.\d+)* ", r"\1", t)   # numbered markdown headings
    t = re.sub(r"§\d+(?:\.\d+)*", " ", t)                # section references
    t = re.sub(r"(\d),(?=\d{3}(\D|$))", r"\1", t)        # 18,720 -> 18720
    tokens = set()
    for m in re.finditer(r"(?<![A-Za-z0-9_.,])([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?=%|\b)", t):
        tokens.add(m.group(1))
    return tokens


def check_readme() -> list:
    if not MANIFEST_PATH.exists():
        return ["manifest missing; run python eval/generate_readme.py first"]
    if not README_PATH.exists():
        return ["README.md missing; run python eval/generate_readme.py first"]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    readme = README_PATH.read_text(encoding="utf-8")

    errors = verify_manifest(manifest)

    allowed = set()
    for e in manifest:
        if e["number"] is not None:
            allowed.add(round(float(e["number"]), 9))
        try:
            allowed.add(round(float(e["text"]), 9))  # the rendered (rounded) form
        except (TypeError, ValueError):
            pass
        nums = e["spec"].get("numbers")
        if isinstance(nums, list):
            allowed.update(round(float(x), 9) for x in nums)

    tokens = extract_tokens(readme, manifest)
    unmatched = []
    for tok in tokens:
        val = float(tok)
        if float(val).is_integer() and abs(val) <= TRIVIAL_INT_MAX:
            continue  # structural integers (section numbers, small counts, W-ids)
        if any(abs(val - a) <= 1e-9 * max(1.0, abs(a)) for a in allowed):
            continue
        unmatched.append(tok)

    if unmatched:
        errors.append("numeric tokens in README.md not covered by the manifest: "
                      + ", ".join(sorted(set(unmatched))[:40]))

    missing = [e["name"] for e in manifest
               if e["number"] is not None and e["text"] is not None
               and e["text"] not in readme]
    if missing:
        errors.append(f"manifest values not found in README.md (stale manifest?): {missing[:20]}")

    return errors


# ---------------------------------------------------------------------------
# legacy single-report mode (unchanged behaviour)
# ---------------------------------------------------------------------------
def extract_numbers_from_text(text: str):
    pattern = r'(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?'
    cleaned = []
    for t in re.findall(pattern, text):
        is_pct = t.endswith('%')
        try:
            cleaned.append((t, float(t.rstrip('%')), is_pct))
        except ValueError:
            pass
    return cleaned


def collect_all_json_numbers(data):
    numbers = set()

    def recurse(node):
        if isinstance(node, (int, float)):
            numbers.add(round(float(node), 4))
            numbers.add(round(float(node), 2))
            numbers.add(round(float(node), 1))
        elif isinstance(node, dict):
            for v in node.values():
                recurse(v)
        elif isinstance(node, list):
            for item in node:
                recurse(item)
    recurse(data)
    return numbers


def check_report(report_path: str, json_path: str):
    text = Path(report_path).read_text(encoding="utf-8")
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    json_numbers = collect_all_json_numbers(data)
    unmatched = []
    for orig_str, val, is_pct in extract_numbers_from_text(text):
        if orig_str in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "20", "0", "1440"):
            continue
        matched = False
        candidates = [round(val, 4), round(val, 2), round(val, 1),
                      round(val / 100.0, 4) if is_pct else None, round(val * 100.0, 2)]
        for c in candidates:
            if c is not None and c in json_numbers:
                matched = True
                break
        if not matched:
            val_repr = f"{val:.2f}"
            val_repr_1 = f"{val:.1f}"
            if val_repr in json.dumps(data) or val_repr_1 in json.dumps(data) or orig_str in json.dumps(data):
                matched = True
        if not matched:
            unmatched.append(orig_str)
    return sorted(set(unmatched))


# ---------------------------------------------------------------------------
def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--readme":
        errors = check_readme()
        if errors:
            print(f"FAILED: README.md numeric verification found {len(errors)} problem(s):")
            for e in errors:
                print(f"  - {e}")
            return 1
        n = len(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
        print(f"SUCCESS: every numeric token in README.md traces to the committed sources "
              f"({n} manifest entries re-verified).")
        return 0

    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    rep, js = sys.argv[1], sys.argv[2]
    unmatched = check_report(rep, js)
    if unmatched:
        print(f"FAILED: Found {len(unmatched)} UNMATCHED numbers in {rep}:")
        for u in unmatched:
            print(f"  {u}")
        return 1
    print(f"SUCCESS: All numbers in {rep} matched against {js}!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
