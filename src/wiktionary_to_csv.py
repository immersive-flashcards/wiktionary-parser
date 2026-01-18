"""Script to convert verb data from Wiktionary JSONL dumps into CSV files."""

import collections
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import zstandard as zstd

import polars as pl
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent


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
    person_map: dict[str, Any]
    pronouns: dict[str, Any]
    base_forms: dict[str, Any]


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
        auxiliary=data.get("auxiliary", "haber"),
        category_config=data["category_config"],
        row_meta=data["row_meta"],
        row_order=data["row_order"],
        person_map=data.get("person_map", {}),
        pronouns=data.get("pronouns", {}),
        base_forms=data.get("base_forms", {}),
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
        "masculine",
        "feminine",
        "masculine-form",
        "feminine-form",
        "table-tags",
        "inflection-template",
        "formal",
    }
    return tuple(sorted(t for t in tags if t not in ignore))


def person_index(tags, lang_cfg: LanguageConfig) -> int | None:
    """
    Config-driven mapping from Kaikki tags to a grammatical person index.

    person_map:
      rules:
        - idx: <int>
          all: [..]   # must all be present
          any: [..]   # at least one present (optional)
          none: [..]  # must NOT be present (optional)
    """
    tagset = set(tags or [])

    for r in lang_cfg.person_map.get("rules", []):
        idx = r.get("idx")
        if idx is None:
            continue

        all_tags = set(r.get("all", []))

        # future-proofing- not currently needed for ES or CA
        # any_tags = set(r.get("any", []))
        # none_tags = set(r.get("none", []))

        if all_tags and not all_tags.issubset(tagset):
            continue
        # if any_tags and not (any_tags & tagset):
        #     continue
        # if none_tags and (none_tags & tagset):
        #     continue

        return int(idx)

    return None


def split_refl(form_str, cfg: dict):
    """Split off a leading reflexive pronoun (Spanish: me/te/se/nos/os)."""

    for rp in cfg.get("reflexive-pronouns"):
        if form_str.startswith(rp):
            return rp, form_str[len(rp) :]

    return None, form_str


def get_base_infinitive(entry: dict, cfg: dict) -> tuple[str, str]:
    """Return a normalized base infinitive, e.g. stripping reflexive 'se' for Spanish."""
    lemma = entry.get("word", "") or ""

    for rs in cfg.get("reflexive-suffixes"):
        if lemma.endswith(rs):
            return lemma[: -(len(rs))], "True"

    return lemma, "False"


def pronoun_for_idx(idx: int, lang_cfg: LanguageConfig) -> str | None:
    """Return pronoun string for given person index."""
    by_idx = (lang_cfg.pronouns or {}).get("by_idx", {}) or {}
    val = by_idx.get(idx)
    return val if val else None


def maybe_merge_voseo(by_idx: dict[int, list[dict]], row: dict[str, str | None], lang_cfg: LanguageConfig) -> None:
    """Merge tú and vos forms when identical, per language config."""
    vcfg = (lang_cfg.pronouns or {}).get("voseo", {}) or {}
    if not vcfg.get("merge_when_same_form", False):
        return

    merge_into = int(vcfg.get("merge_into_idx", 2))
    drop_idx = int(vcfg.get("drop_idx", 7))

    if merge_into not in by_idx or drop_idx not in by_idx:
        return

    f2 = by_idx[merge_into][0]
    f7 = by_idx[drop_idx][0]

    refl2, verb2 = split_refl(f2["form"], lang_cfg.category_config)
    refl7, verb7 = split_refl(f7["form"], lang_cfg.category_config)

    if verb2 != verb7:
        return

    p2 = pronoun_for_idx(merge_into, lang_cfg)
    p7 = pronoun_for_idx(drop_idx, lang_cfg)
    merged_pron = merge_pronouns(p2, p7)

    if merged_pron:
        row[f"pronoun-{merge_into}"] = merged_pron

    merged_refl = refl2 or refl7
    if merged_refl:
        row[f"refl_pronoun-{merge_into}"] = merged_refl

    row[f"conjugation-{merge_into}"] = verb2

    del by_idx[drop_idx]


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


def build_header(lang_cfg: LanguageConfig) -> list[str]:
    """Build CSV header row."""
    header = ["", "mode"]
    for i in range(1, len(lang_cfg.pronouns.get("by_idx")) + 1):  # no of csv-columns by no. of pronouns in language
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
        return {}  # for now: silently ignore entries from other languages

    cats = entry.get("categories", []) or []
    cat_names = [c.get("name") for c in cats if isinstance(c, dict) and c.get("name")]

    # enwiktionary style: categories can also appear per sense
    for s in entry.get("senses", []) or []:
        for c in s.get("categories", []) or []:
            if isinstance(c, dict) and c.get("name"):
                cat_names.append(c["name"])

    cat_names = sorted(set(cat_names))

    cfg = lang_cfg.category_config

    result: dict[str, list[str]] = {}

    base_infinitive, reflexive_bool = get_base_infinitive(entry, cfg)
    result["base_infinitive"] = [base_infinitive]
    result["reflexive"] = [reflexive_bool]
    result["auxiliary"] = [lang_cfg.auxiliary]

    for row_label, conf in cfg.items():
        # Case 1: prefix-based extractor, e.g. "paradigma": {"prefix": "ES:Verbos del paradigma "}
        if isinstance(conf, dict) and "prefix" in conf:
            prefix = conf["prefix"]
            for cat in cat_names:
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
            for cat in cat_names:
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


def build_csv_for_entry(entry: dict, header, lang_cfg: LanguageConfig, run_cfg: RunConfig):
    """Build CSV file for a single verb entry."""
    lemma = entry.get("word")
    forms = entry.get("forms", [])

    # group forms by tense-key
    forms_by_key = collections.defaultdict(list)
    for f in forms:
        tags = f.get("tags", []) or []
        # skip conjugation table artifacts
        if "table-tags" in tags or "inflection-template" in tags:
            continue
        tk = tense_key(tags)
        forms_by_key[tk].append(f)

    row_meta = lang_cfg.row_meta
    row_order = lang_cfg.row_order

    rows: list[dict[str, str | None]] = []

    for key in row_order:
        meta = row_meta[key]
        row = {h: None for h in header}
        row[""] = meta["label"]
        row["mode"] = meta["mode"]

        if key == lang_cfg.base_forms.get("infinitive"):
            row["conjunction-1"] = lemma

        elif key == lang_cfg.base_forms.get("gerund"):
            g_forms = forms_by_key.get(tuple(meta["key"]), [])
            if g_forms:
                chosen = min(g_forms, key=lambda f: len(f["form"]))
                row["conjunction-1"] = chosen["form"]

        elif key == lang_cfg.base_forms.get("participle"):
            p_forms = forms_by_key.get(tuple(meta["key"]), [])
            if p_forms:
                # Prefer the canonical past participle (avoid gender/number variants if present)
                def score_pf(f: dict) -> tuple[int, int]:
                    t = set(f.get("tags", []) or [])
                    # best: exactly participle+past
                    exact = 0 if t == {"participle", "past"} else 1
                    # then shortest string
                    return (exact, len(f["form"]))

                chosen = min(p_forms, key=score_pf)
                row["conjunction-1"] = chosen["form"]

        else:
            if key == "imp_negativo" and meta["key"] is None:
                # Spanish-style: negative imperative not present as its own forms, reuse subjunctive present
                tk = tuple(row_meta["subj_presente"]["key"])
            else:
                tk = tuple(meta["key"]) if meta["key"] is not None else tuple()

            f_list = forms_by_key.get(tk, [])

            by_idx: dict[int, list[dict]] = collections.defaultdict(list)
            for f in f_list:
                idx = person_index(f["tags"], lang_cfg)
                if idx:
                    by_idx[idx].append(f)

            # special case: merge tú + vos when identical
            maybe_merge_voseo(by_idx, row, lang_cfg)

            for idx, flist in by_idx.items():
                if key == "imp_negativo" and idx == 1:
                    continue

                for f in flist:
                    conj = f["form"]
                    refl, verb = split_refl(conj, lang_cfg.category_config)

                    # Catalan explicit negative imperative comes as "no <verb>"
                    if key == "imp_negativo" and meta["key"] is not None:
                        if verb.startswith("no "):
                            row[f"negation-{idx}"] = "no "
                            verb = verb[3:]

                    pron = pronoun_for_idx(idx, lang_cfg)

                    c_pron = f"pronoun-{idx}"
                    c_neg = f"negation-{idx}"
                    c_refl = f"refl_pronoun-{idx}"
                    c_verb = f"conjugation-{idx}"

                    if pron and row.get(c_pron) is None:
                        row[c_pron] = pron
                    if refl and row.get(c_refl) is None:
                        row[c_refl] = refl

                    if key == "imp_negativo" and meta["key"] is None and row.get(c_neg) is None:
                        row[c_neg] = "no "

                    existing = row.get(c_verb)
                    if existing is None:
                        row[c_verb] = verb
                    else:
                        variants = {v.strip() for v in existing.split("/") if v.strip()}
                        variants.add(verb.strip())
                        row[c_verb] = " / ".join(sorted(variants))

        rows.append(row)

    out_path = run_cfg.output_dir / lang_cfg.output_dir
    out_path.mkdir(parents=True, exist_ok=True)
    out_file = out_path / f"{lemma}.csv"

    schema = {col: pl.Utf8 for col in header}
    df_conj = pl.DataFrame(rows, schema=schema, orient="row")

    df_meta = build_metadata_df(entry, header, lang_cfg)
    if df_meta is not None:
        df_meta = df_meta.cast(schema)
        df_final = pl.concat([df_conj, df_meta], how="vertical")
    else:
        df_final = df_conj

    df_final.write_csv(out_file, separator=";")
    print(f"Wrote CSV to {out_file}")


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
