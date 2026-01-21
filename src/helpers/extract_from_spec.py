"""Helper function to extract values from nested dictionaries based on a specification."""

from typing import Any


def _get_by_path(obj: Any, path: list[str]) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def extract_from_spec(entry: dict[str, Any], spec: dict[str, Any], tag_alts: list[list[str]] | None) -> list[str] | None:
    """Helper function to extract values from nested dictionaries based on a specification."""
    target = _get_by_path(entry, spec["path"])

    # Simple case: direct value
    if tag_alts == [None]:
        return [target] if isinstance(target, str) else None

    # Tagged case: list lookup
    needed_sets = [set(t) for t in tag_alts]
    if not isinstance(target, list):
        return None

    matches: list[str] = []
    for item in target:
        if not isinstance(item, dict):
            continue
        item_tags = set(item.get("tags", []) or [])
        if any(ns == item_tags for ns in needed_sets):
            form = item.get("form")
            if isinstance(form, str) and form.strip():
                matches.append(form.strip())

    if not matches:
        return None

    if spec.get("on_collision") == "shortest_length":
        return [min(matches, key=len)]

    return matches
