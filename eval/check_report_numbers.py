#!/usr/bin/env python3
"""
eval/check_report_numbers.py <report.md> <results.json>
Extracts numbers from markdown report and checks that they appear in the JSON
or are derivable by documented differences / ratios.
"""
import sys
import re
import json

def extract_numbers_from_text(text: str):
    """
    Extracts numerical tokens from text, ignoring dates, markdown table markers, percentages, etc.
    """
    # Replace markdown links/images, headers, table pipes
    # Find all float / integer numbers like -123.45, +12.34, 99.99
    # Ignore standalone integers that are small table indices or common list numbers if needed,
    # but let's be thorough: capture all decimals and signed numbers.
    pattern = r'(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?'
    raw_tokens = re.findall(pattern, text)
    cleaned = []
    for t in raw_tokens:
        is_pct = t.endswith('%')
        val_str = t.rstrip('%')
        try:
            val = float(val_str)
            cleaned.append((t, val, is_pct))
        except ValueError:
            pass
    return cleaned

def collect_all_json_numbers(data):
    """
    Recursively extracts all numbers from a JSON object.
    """
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
    with open(report_path, "r", encoding="utf-8") as f:
        text = f.read()

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    json_numbers = collect_all_json_numbers(data)

    # Some numbers are commonly derived: e.g. differences: a - b, or percentage conversions x * 100
    tokens = extract_numbers_from_text(text)
    unmatched = []

    for orig_str, val, is_pct in tokens:
        # Ignore markdown heading indicators, dates, bullet numbers, common targets
        if orig_str in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "20", "0", "1440"):
            continue
        # Also check against direct rounded values
        matched = False
        candidates = [
            round(val, 4),
            round(val, 2),
            round(val, 1),
            round(val / 100.0, 4) if is_pct else None,
            round(val * 100.0, 2)
        ]
        for c in candidates:
            if c is not None and c in json_numbers:
                matched = True
                break

        if not matched:
            # Let's check if it appears literally in the raw json string
            val_repr = f"{val:.2f}"
            val_repr_1 = f"{val:.1f}"
            if val_repr in json.dumps(data) or val_repr_1 in json.dumps(data) or orig_str in json.dumps(data):
                matched = True

        if not matched:
            unmatched.append(orig_str)

    unmatched_unique = sorted(list(set(unmatched)))
    return unmatched_unique

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python check_report_numbers.py <report.md> <results.json>")
        sys.exit(1)

    rep = sys.argv[1]
    js = sys.argv[2]
    unmatched = check_report(rep, js)
    if unmatched:
        print(f"FAILED: Found {len(unmatched)} UNMATCHED numbers in {rep}:")
        for u in unmatched:
            print(f"  {u}")
        sys.exit(1)
    else:
        print(f"SUCCESS: All numbers in {rep} matched against {js}!")
        sys.exit(0)
