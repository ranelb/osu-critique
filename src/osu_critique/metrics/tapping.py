"""Tapping style metrics: alternation, same-key adjacencies, key balance."""
from __future__ import annotations


def tapping_stats(results):
    all_keys = [x["key"] for x in results if x["key"]]
    same_adj = sum(1 for a, b in zip(all_keys, all_keys[1:]) if a == b)
    return {"n": len(all_keys),
            "same_key_adjacent": same_adj,
            "same_key_pct": same_adj / max(1, len(all_keys) - 1),
            "alt_ratio": 1 - same_adj / max(1, len(all_keys) - 1)}


def key_usage(results):
    return {"A": sum(1 for x in results if x["key"] == "A"),
            "B": sum(1 for x in results if x["key"] == "B")}
