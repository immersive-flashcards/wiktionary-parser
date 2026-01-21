"""Script to convert verb data from Wiktionary JSONL dumps into CSV files."""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import unicodedata

import polars as pl
import yaml
import zstandard as zstd

from src.language_functions.es import merge_tu_vos_if_equal, create_spanish_negative_imperative
from src.language_functions.ca import add_catalan_category_tags
from src.helpers.extract_from_spec import extract_from_spec

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class LanguageConfig:
    """Configuration data for a specific language"""

    lang_code: str
    infinitives_jsonl: Path
    meta_data: dict[str, Any]
    person_data: dict[str, Any]
    category_source: dict[str, Any]
    category_data: dict[str, Any]
    complex_category_data: dict[str, Any]
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
        meta_data=data.get("meta-data", {}),
        person_data=data.get("person-data", {}),
        category_source=data.get("category_source", {}),
        category_data=data["category_data"],
        complex_category_data=data.get("complex_category_data", {}),
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


def build_header(lang_cfg: LanguageConfig) -> list[str]:
    """Build CSV header row."""
    header = ["key", "mode"]
    for i in range(1, len(lang_cfg.person_data.get("pronouns")) + 1):  # no of csv-columns by no. of pronouns in language
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


def _get_base_infinitive_and_reflexivity(infinitive: str, meta_data: dict[str, Any]) -> tuple[str, bool]:
    # Handle reflexive suffixes (e.g. Spanish, Catalan, Italian)
    refl_suffixes = meta_data.get("reflexive-suffixes")
    if refl_suffixes:
        for suffix in refl_suffixes:
            if infinitive.endswith(suffix):
                return infinitive[: -len(suffix)], True

    # TODO: Handle reflexive prefixes (e.g. French)

    return infinitive, False


def _get_stem(base_infinitive: str, meta_data: dict[str, Any]) -> tuple[str, str]:
    def _normalize(s: str) -> str:
        normalized = unicodedata.normalize("NFKD", s)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    for suffix in meta_data.get("endings"):
        if _normalize(base_infinitive).endswith(suffix):
            return base_infinitive[: -len(suffix)], suffix
    return "", ""


def _get_auxiliary(lang_cfg: LanguageConfig) -> str:
    aux_config = lang_cfg.meta_data.get("auxiliary")
    if isinstance(aux_config, str):  # Spanish, catalan,etc.
        return aux_config
    # TODO: implement for French, Italian, etc.
    return ""


def _merge_identical_verb_forms(lang_cfg: LanguageConfig, row: dict[str, Any]) -> None:
    """Language-specific mergin of identical verb forms. Example: Many Spanish tú/vos forms."""
    if lang_cfg.lang_code == "es":  # Spanish
        merge_tu_vos_if_equal(row)


def _add_missing_forms(lang_config: LanguageConfig, entry: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Add missing verb forms that are not in the JSONL. Example: Spanish negative imperative."""
    if lang_config.lang_code == "es":  # Spanish
        create_spanish_negative_imperative(rows)
    if lang_config.lang_code == "ca":  # Catalan
        add_catalan_category_tags(entry, rows)


# Helper to get category list from entry - can be nested
def extract_categories(entry: dict, lang_cfg: LanguageConfig) -> set[str]:
    """Extract categories as set according to config. Can be a list or a nested list of dicts"""
    path = lang_cfg.category_source["path"]
    item_spec = lang_cfg.category_source["item"]

    if path == ["categories"]:
        cats = entry["categories"]  # list[str]
        return set(cats)

    if path == ["senses", "*", "categories"]:
        senses = entry["senses"]  # list[dict]
        cats = (c for s in senses for c in s.get("categories", []))  # list[dict]
        name_key = item_spec["key"]
        return {c[name_key] for c in cats}

    raise ValueError(f"Unsupported category path: {path!r}")


def build_csv_for_entry(entry: dict[str, Any], header: list[str], lang_cfg: LanguageConfig, run_cfg: RunConfig) -> None:
    """Write the config-selected values into a per-verb CSV"""
    lemma = entry.get("word")
    rows_out: list[dict[str, Any]] = []

    # Add verb form rows
    person_data = lang_cfg.person_data
    person_map = person_data["person_map"]
    refl_pronouns_by_i = person_data.get("reflexive-pronouns", [])

    for row_key, form in lang_cfg.forms.items():
        row_to_add = {"key": row_key, "mode": form["mode"]}

        # Handle base forms (infinitive, gerund, participle)
        if form.get("type") == "base_form":
            f = extract_from_spec(entry, form, [form.get("tags")])
            row_to_add["conjunction-1"] = f[0] if f else ""
            _merge_identical_verb_forms(lang_cfg, row_to_add)
            rows_out.append(row_to_add)
            continue

        # Handle tag-based conjugations
        form_tags = form.get("tags") or []
        negation = form.get("negation")

        for i, person_alts in person_map.items():
            tag_alts = [form_tags + alt for alt in person_alts]
            f_list = extract_from_spec(entry, form, tag_alts)
            if not f_list:
                continue

            # Split off negation if present and indicated by config
            if negation:
                for idx, f in enumerate(f_list):
                    if f.startswith(negation):
                        f_list[idx] = f[len(negation) :]
                        row_to_add[f"negation-{i}"] = negation

            # Split off reflexive pronoun if present
            reflexive_alts = refl_pronouns_by_i[i - 1] if i - 1 < len(refl_pronouns_by_i) else []
            for rp in reflexive_alts:
                for idx, f in enumerate(f_list):
                    if f.startswith(rp):
                        f_list[idx] = f[len(rp) :]
                        row_to_add[f"refl_pronoun-{i}"] = rp

                # Join multiple equivalent forms with " / "
                conjugation = f_list[0] if len(f_list) == 1 else " / ".join(f_list)

                row_to_add[f"conjugation-{i}"] = conjugation if conjugation is not None else ""

                if form.get("pronouns") == "imperative":
                    row_to_add[f"pronoun-{i}"] = lang_cfg.person_data.get("imperative-pronouns").get(i)
                else:
                    row_to_add[f"pronoun-{i}"] = lang_cfg.person_data.get("pronouns").get(i)

        _merge_identical_verb_forms(lang_cfg, row_to_add)

        rows_out.append(row_to_add)

    _add_missing_forms(lang_cfg, entry, rows_out)  # forms that are not in the jsonl input

    # Add metadata rows
    auxiliary = _get_auxiliary(lang_cfg)
    base_infinitive, reflexive = _get_base_infinitive_and_reflexivity(lemma, lang_cfg.meta_data)
    stem, ending = _get_stem(base_infinitive, lang_cfg.meta_data)

    meta_items = {
        "auxiliary": auxiliary,
        "reflexive": reflexive,
        "base_infinitive": base_infinitive,
        "stem": stem,
        "ending": ending,
    }
    rows_out.extend({"key": k, "mode": v} for k, v in meta_items.items())

    # Add category data rows
    category_list = extract_categories(entry, lang_cfg)

    # fmt: off
    # 1. Checks for exact match with categories listed in entry
    for cat, options in lang_cfg.category_data.items():
        rows_out.extend(
            {"key": cat, "mode": v}
            for k, v in options.items()
            if k in category_list
        )

    # 2. Add complex category matches
    for cat, instruction in lang_cfg.complex_category_data.items():
        if prefix := instruction.get("startswith"):
            rows_out.extend(
                {"key": cat, "mode": c[len(prefix):].strip()}
                for c in category_list
                if c.startswith(prefix)
            )
    # fmt: on

    # Write out CSV
    out_dir = (run_cfg.output_dir / lang_cfg.lang_code).resolve()
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
