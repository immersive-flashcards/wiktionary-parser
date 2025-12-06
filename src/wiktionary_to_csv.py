"""Script to convert verb data from Wiktionary JSONL dumps into CSV files."""

import collections
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml


@dataclass
class LanguageConfig:
    """Configuration data for a specific language"""

    lang_code: str
    infinitives_jsonl: Path
    output_dir: Path
    auxiliary: str
    category_config: dict[str, Any]
    row_meta: dict[str, dict[str, Any]]
    row_order: list[str]


@dataclass
class RunConfig:
    """Configuration data for dev / prod / test runs"""

    profile: str
    max_verbs: int | None
    languages: list[str]


def _load_language_config(lang_code: str) -> LanguageConfig:
    cfg_path = Path("config/languages") / f"{lang_code}.yml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    return LanguageConfig(
        lang_code=data["lang_code"],
        infinitives_jsonl=Path(data["infinitives_jsonl"]),
        output_dir=Path(data["output_dir"]),
        auxiliary=data.get("auxiliary", "haber"),
        category_config=data["category_config"],
        row_meta=data["row_meta"],
        row_order=data["row_order"],
    )


def _load_run_config(profile: str) -> RunConfig:
    cfg_path = Path("config/runs") / f"{profile}.yml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    return RunConfig(
        profile=data["profile"],
        max_verbs=data.get("max_verbs", None),
        languages=data["languages"],
    )


def tense_key(tags):
    """Return a normalized key for tense/mood/aspect ignoring person/number."""
    ignore = {
        "first-person",
        "second-person",
        "third-person",
        "singular",
        "plural",
        "vos-form",
        "impersonal",
        "informal",
        "formal",
        "masculine",
        "feminine",
        "masculine-form",
        "feminine-form",
    }
    return tuple(sorted(t for t in tags if t not in ignore))


def person_index(tags):
    """
    Map Kaikki tags to a person slot:
      1: 1sg, 2: 2sg-tú, 3: 3sg, 4: 1pl, 5: 2pl, 6: 3pl, 7: 2sg-voseo.
    """
    is_vos = "vos-form" in tags

    if "first-person" in tags and "singular" in tags:
        return 1
    if "first-person" in tags and "plural" in tags:
        return 4
    if "second-person" in tags and "singular" in tags:
        return 7 if is_vos else 2
    if "second-person" in tags and "plural" in tags:
        return 5
    if "third-person" in tags and "singular" in tags:
        return 3
    if "third-person" in tags and "plural" in tags:
        return 6
    return None


def split_refl(form_str):
    """Split off a leading reflexive pronoun (me/te/se/nos/os) when it's a separate token."""
    refls = {"me", "te", "se", "nos", "os"}
    parts = form_str.split()
    if parts and parts[0] in refls:
        return parts[0] + " ", " ".join(parts[1:])
    return None, form_str


def get_base_infinitive(entry: dict) -> tuple[str, str]:
    """Return a normalized base infinitive, e.g. stripping reflexive 'se' for Spanish."""
    lemma = entry.get("word", "") or ""
    lang = entry.get("lang_code")

    # Spanish reflexive infinitives. Examples: meterse -> meter, irse -> ir
    if lang == "es" and lemma.endswith("se"):
        return lemma[:-2], "True"

    return lemma, "False"


def normalize_pronoun(raw_tags):
    """Normalize raw_tags into something like 'él //ella //usted '."""
    if not raw_tags:
        return None

    s = raw_tags[0]
    s = s.replace("que ", "")  # remove 'que ' from subjunctive labels
    s = s.strip()

    if "ustedes" in s and "ellos" in s and "ellas" not in s:
        s = s.replace("ellos", "ellos, ellas")

    s = s.replace(", ", " //")  # parser expects double slashes
    return s + " "  # trailing whitespace for consistency


def merge_pronouns(p2: str | None, p7: str | None) -> str | None:
    """
    Merge pronoun strings for tú and vos when forms are identical (most forms - only present and imperative differ)
    So: 'tú ' and 'vos ' -> 'tú //vos '.
    """
    if not p2 and not p7:
        return None
    if p2 and not p7:
        return p2
    if p7 and not p2:
        return p7

    def split_pron(p: str) -> list[str]:
        return [part for part in p.strip().split(" //") if part]

    parts: list[str] = []
    for part in split_pron(p2):
        if part not in parts:
            parts.append(part)
    for part in split_pron(p7):
        if part not in parts:
            parts.append(part)

    return " //".join(parts) + " " if parts else None


def build_header() -> list[str]:
    """Build CSV header row."""
    header = ["", "mode"]
    for i in range(1, 8):
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


def extract_metadata(entry: dict, lang_cfg: LanguageConfig) -> dict[str, list[str]]:
    """
    Read entry['categories'] and return something like:
      {
        "categories": ["tercera conjugación", "irregular", "transitivo"],
        "paradigma": ["dar"],
        "base_infinitive": ["meter"],
        "reflexive": ["True"],
        "auxiliary": ["haber"],
        "endings": ["er"],
        "stem": ["met"],
      }
    """
    lang_code = entry.get("lang_code")
    if lang_code != lang_cfg.lang_code:
        return {}   # for now: silently ignore entries from other languages

    cats = entry.get("categories", []) or []
    cfg = lang_cfg.category_config

    result: dict[str, list[str]] = {}

    base_infinitive, reflexive_bool = get_base_infinitive(entry)
    result["base_infinitive"] = [base_infinitive]
    result["reflexive"] = [reflexive_bool]
    result["auxiliary"] = [lang_cfg.auxiliary]

    for row_label, conf in cfg.items():
        # Case 1: prefix-based extractor, e.g. "paradigma": {"prefix": "ES:Verbos del paradigma "}
        if isinstance(conf, dict) and "prefix" in conf:
            prefix = conf["prefix"]
            for cat in cats:
                if cat.startswith(prefix):
                    suffix = cat[len(prefix) :].strip()
                    if not suffix:
                        continue
                    lst = result.setdefault(row_label, [])
                    if suffix not in lst:
                        lst.append(suffix)

        # Case 2: simple mapping from full category → normalized tag
        if isinstance(conf, dict) and "prefix" not in conf:
            mapping = conf
            values = result.setdefault(row_label, [])
            for cat in cats:
                if cat in mapping:
                    val = mapping[cat]
                    if val not in values:
                        values.append(val)
            continue

        # Case 3: endings → choose first matching
        if isinstance(conf, list):
            for ending in conf:
                if base_infinitive.endswith(ending):
                    lst = result.setdefault(row_label, [])
                    lst.append(ending)
                    result["stem"] = [base_infinitive[: -len(ending)]]
                    break

    return result


def build_metadata_df(entry: dict, header: list[str], lang_cfg: LanguageConfig) -> pl.DataFrame | None:
    """Build a Polars DataFrame for the metadata rows."""
    meta_map = extract_metadata(entry, lang_cfg)
    if not meta_map:
        return None

    rows: list[list[str | None]] = []

    for row_label, values in meta_map.items():
        if not values:
            continue

        row_vals: list[str | None] = [row_label, *values]
        if len(row_vals) < len(header):
            row_vals.extend([None] * (len(header) - len(row_vals)))
        else:
            row_vals = row_vals[: len(header)]

        rows.append(row_vals)

    if not rows:
        return None

    schema = {col: pl.Utf8 for col in header}
    return pl.DataFrame(rows, schema=schema, orient="row")


def build_csv_for_entry(entry: dict, header, lang_cfg: LanguageConfig):
    """Build CSV file for a single verb entry."""
    lemma = entry.get("word")
    forms = entry.get("forms", [])

    # group forms by tense-key
    forms_by_key = collections.defaultdict(list)
    for f in forms:
        tk = tense_key(f["tags"])
        forms_by_key[tk].append(f)

    row_meta = lang_cfg.row_meta
    row_order = lang_cfg.row_order

    rows: list[dict[str, str | None]] = []

    for key in row_order:
        meta = row_meta[key]
        row = {h: None for h in header}
        row[""] = meta["label"]
        row["mode"] = meta["mode"]

        if key == "infinitivo":
            row["conjunction-1"] = lemma

        elif key == "gerundio":
            g_forms = forms_by_key.get(tuple(meta["key"]), [])
            if g_forms:
                chosen = min(g_forms, key=lambda f: len(f["form"]))
                row["conjunction-1"] = chosen["form"]

        elif key == "participio":
            p_forms = forms_by_key.get(tuple(meta["key"]), [])
            if p_forms:
                row["conjunction-1"] = p_forms[0]["form"]

        else:
            if key == "imp_negativo":
                tk = tuple(row_meta["subj_presente"]["key"])
            else:
                tk = tuple(meta["key"])

            f_list = forms_by_key.get(tk, [])

            by_idx: dict[int, list[dict]] = collections.defaultdict(list)
            for f in f_list:
                idx = person_index(f["tags"])
                if idx:
                    by_idx[idx].append(f)

            # special case: merge tú + vos when identical
            if 2 in by_idx and 7 in by_idx:
                f2 = by_idx[2][0]
                f7 = by_idx[7][0]

                refl2, verb2 = split_refl(f2["form"])
                refl7, verb7 = split_refl(f7["form"])

                if verb2 == verb7:
                    p2 = normalize_pronoun(f2.get("raw_tags", []))
                    p7 = normalize_pronoun(f7.get("raw_tags", []))
                    merged_pron = merge_pronouns(p2, p7)

                    merged_refl = refl2 or refl7
                    chosen_verb = verb2

                    c_pron2 = "pronoun-2"
                    c_refl2 = "refl_pronoun-2"
                    c_verb2 = "conjugation-2"

                    if merged_pron:
                        row[c_pron2] = merged_pron
                    if merged_refl:
                        row[c_refl2] = merged_refl
                    row[c_verb2] = chosen_verb

                    del by_idx[7]

            for idx, flist in by_idx.items():
                if key == "imp_negativo" and idx == 1:
                    continue

                for f in flist:
                    conj = f["form"]
                    refl, verb = split_refl(conj)
                    pron = normalize_pronoun(f.get("raw_tags", []))

                    c_pron = f"pronoun-{idx}"
                    c_neg = f"negation-{idx}"
                    c_refl = f"refl_pronoun-{idx}"
                    c_verb = f"conjugation-{idx}"

                    if pron and row.get(c_pron) is None:
                        row[c_pron] = pron
                    if refl and row.get(c_refl) is None:
                        row[c_refl] = refl

                    if key == "imp_negativo" and row.get(c_neg) is None:
                        row[c_neg] = "no "

                    existing = row.get(c_verb)
                    if existing is None:
                        row[c_verb] = verb
                    else:
                        variants = {v.strip() for v in existing.split("/") if v.strip()}
                        variants.add(verb.strip())
                        row[c_verb] = " / ".join(sorted(variants))

        rows.append(row)

    lang_cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = lang_cfg.output_dir / f"{lemma}.csv"

    schema = {col: pl.Utf8 for col in header}
    df_conj = pl.DataFrame(rows, schema=schema, orient="row")

    df_meta = build_metadata_df(entry, header, lang_cfg)
    if df_meta is not None:
        df_meta = df_meta.cast(schema)
        df_final = pl.concat([df_conj, df_meta], how="vertical")
    else:
        df_final = df_conj

    df_final.write_csv(out_path, separator=";")
    print(f"Wrote CSV to {out_path}")


def run_for_language(lang_cfg: LanguageConfig, max_verbs: int | None):
    """Run CSV generation for a single language."""
    header = build_header()
    count = 0

    with lang_cfg.infinitives_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)
            build_csv_for_entry(entry, header, lang_cfg)

            count += 1
            if max_verbs is not None and count >= max_verbs:
                print(f"[{lang_cfg.lang_code}] Stopped after {max_verbs} verbs.")
                break


def main(profile: str = "dev"):
    """"Main function to convert infinitive verbs JSONL into per-verb CSV files."""
    run_cfg = _load_run_config(profile)
    start = time.time()

    for lang_code in run_cfg.languages:
        lang_cfg = _load_language_config(lang_code)
        print(f"Running profile={run_cfg.profile} for language={lang_code}")
        run_for_language(lang_cfg, run_cfg.max_verbs)

    print(f"Completed in {time.time() - start:.2f} seconds.")


if __name__ == "__main__":
    main()
