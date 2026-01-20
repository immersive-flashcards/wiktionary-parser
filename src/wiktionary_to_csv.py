"""Script to convert verb data from Wiktionary JSONL dumps into CSV files."""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml
import zstandard as zstd

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class LanguageConfig:
    """Configuration data for a specific language"""

    lang_code: str
    infinitives_jsonl: Path
    output_dir: Path
    auxiliary: str
    # category_config: dict[str, Any]
    # row_meta: dict[str, dict[str, Any]]
    # csv_row_order: list[str]
    person_map: dict[int, Any]
    pronouns: dict[int, Any]
    endings: list[str]
    reflexive_suffixes: list[str]
    forms: dict[str, Any]


@dataclass
class RunConfig:
    """Configuration data for dev / prod / test runs"""

    profile: str
    max_verbs: int | None
    languages: list[str]
    output_dir: Path


def _load_language_config(lang_code: str) -> LanguageConfig:
    cfg_path = BASE_DIR / "config" / "languages" / f"{lang_code}.yml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    return LanguageConfig(
        lang_code=data["lang_code"],
        infinitives_jsonl=(BASE_DIR / data["infinitives_jsonl"]).resolve(),
        output_dir=Path(data["output_dir"]),
        auxiliary=data.get("auxiliary", ""),
        # category_config=data["category_config"],
        # row_meta=data["row_meta"],
        # csv_row_order=data["csv_row_order"],
        person_map=data.get("person_map", {}),
        pronouns=data.get("pronouns", {}),
        endings=data.get("endings", []),
        reflexive_suffixes=data.get("reflexive-suffixes", []),
        forms=data.get("forms", {}),
    )


def _load_run_config(profile: str) -> RunConfig:
    cfg_path = BASE_DIR / "config" / "runs" / f"{profile}.yml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    return RunConfig(
        profile=data["profile"],
        max_verbs=None if data["max_verbs"] == "None" else data["max_verbs"],
        languages=data["languages"],
        output_dir=(BASE_DIR / data["output_dir"]).resolve(),
    )


def _open_jsonl(path: Path):
    """Open path as text, supporting plain .jsonl and .jsonl.zst."""
    if str(path).endswith(".zst"):
        return zstd.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _get_by_path(obj: Any, path: list[str]) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _extract_from_spec(entry: dict[str, Any], spec: dict[str, Any], tags: list[str] | None) -> str | None:
    target = _get_by_path(entry, spec["path"])

    # Simple case: direct value
    if tags is None:
        return target if isinstance(target, str) else None

    # Tagged case: list lookup
    tags_needed = set(tags)
    if not isinstance(target, list):
        return None

    matches: list[str] = []
    for item in target:
        if not isinstance(item, dict):
            continue
        item_tags = set(item.get("tags", []) or [])
        if tags_needed == item_tags:
            form = item.get("form")
            if isinstance(form, str) and form.strip():
                matches.append(form.strip())

    if not matches:
        return None

    on_collision = spec.get("on_collision")
    if on_collision == "shortest_length":
        return min(matches, key=len)

    return matches[0]


def build_header(lang_cfg: LanguageConfig) -> list[str]:
    """Build CSV header row."""
    header = ["key", "mode"]
    for i in range(1, len(lang_cfg.pronouns) + 1):  # no of csv-columns by no. of pronouns in language
        header.extend(
            [
                f"conjunction-{i}",
                f"pronoun-{i}",
                f"negation-{i}",
                f"refl_pronoun-{i}",
                f"conjugation-{i}",
            ]
        )
    return header


def build_csv_for_entry(entry: dict[str, Any], header: list[str], lang_cfg: LanguageConfig, run_cfg: RunConfig) -> None:
    """Write the config-selected values into a per-verb CSV"""
    lemma = entry.get("word")

    rows_out: list[dict[str, Any]] = []

    for row_key in lang_cfg.forms:
        form = lang_cfg.forms[row_key]

        row_to_add = {
            "key": row_key,
            "mode": lang_cfg.forms[row_key]["mode"],
        }

        # Handle infinitive, gerund, participle forms without pronouns
        if form.get("type") == "base_form":
            val = _extract_from_spec(entry, form, form.get("tags"))
            row_to_add["conjunction-1"] = val if val is not None else ""

        # Handle tag-based conjugations
        else:
            for i, person_tags in lang_cfg.person_map.items():

                val = _extract_from_spec(entry, form, form.get("tags") + person_tags)

                row_to_add[f"conjugation-{i}"] = val if val is not None else ""
                row_to_add[f"pronoun-{i}"] = lang_cfg.pronouns.get(i)

        rows_out.append(row_to_add)

    rs = lang_cfg.reflexive_suffixes[0]

    def _get_base_infinitive_and_reflexivity(infinitive: str, refl_suffixes: list[str]) -> tuple[str, bool]:
        for suffix in refl_suffixes:
            if infinitive.endswith(suffix):
                return infinitive[: -len(suffix)], True
        return infinitive, False

    def _get_stem(base_infinitive: str, endings: list[str]) -> str:
        for suffix in endings:
            if base_infinitive.endswith(suffix):
                return base_infinitive[: -len(suffix)]
        return base_infinitive

    # add base infinitive
    # TODO: turn into generator
    base_infinitive, is_reflexive = _get_base_infinitive_and_reflexivity(lemma, lang_cfg.reflexive_suffixes)
    rows_out.append({"key": "reflexive", "mode": is_reflexive,})
    rows_out.append({"key": "base_infinitive", "mode": base_infinitive,})
    rows_out.append({"key": "stem", "mode": _get_stem(base_infinitive, lang_cfg.endings),})



    out_dir = (run_cfg.output_dir / lang_cfg.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{lemma}.csv"
    df = pl.DataFrame(rows_out, schema=header)
    df.write_csv(out_path, separator=";")


def run_for_language(lang_cfg: LanguageConfig, run_cfg: RunConfig):
    """Run CSV generation for a single language."""
    header = build_header(lang_cfg)
    count = 0

    with _open_jsonl(lang_cfg.infinitives_jsonl) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)
            build_csv_for_entry(entry, header, lang_cfg, run_cfg)

            count += 1
            if run_cfg.max_verbs is not None and count >= run_cfg.max_verbs:
                print(f"[{lang_cfg.lang_code}] Stopped after {run_cfg.max_verbs} verbs.")
                break


def main(profile: str = "dev"):
    """Main function to convert infinitive verbs JSONL into per-verb CSV files."""
    run_cfg = _load_run_config(profile)
    start = time.time()

    for lang_code in run_cfg.languages:
        lang_cfg = _load_language_config(lang_code)
        print(f"Running profile={run_cfg.profile} for language={lang_code}")
        run_for_language(lang_cfg, run_cfg)

    print(f"Completed in {time.time() - start:.2f} seconds.")


if __name__ == "__main__":
    # Use first CLI arg as profile if present
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        main()
