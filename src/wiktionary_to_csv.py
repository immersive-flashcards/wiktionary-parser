"""Script to convert verb data from Wiktionary JSONL dumps into CSV files."""

import collections
import json
import time
from pathlib import Path
import polars as pl

INFINITIVES_JSONL = Path("data/language-verb-dumps/es-infinitives.jsonl")
OUTPUT_DIR = Path("data/verb-csvs/spanish")
MAX_VERBS: int | None = 25  # max verbs to extract for quick tests, or None for all verbs


CATEGORY_CONFIG = {  # per-language mapping from Wiktionary categories to normalized tags
    "es": {  # only Spanish for now
        # 1) Simple lookups → "key" row
        "categories": {  # currently a catch-all for verb categories: may all be distributed to their own rows eventually
            "ES:Verbos intransitivos": "intransitivo",
            "ES:Verbos transitivos": "transitivo",
        },
        "verb-group": {
            "ES:Verbos de la primera conjugación": "primera conjugación",
            "ES:Verbos de la segunda conjugación": "segunda conjugación",
            "ES:Verbos de la tercera conjugación": "tercera conjugación",
        },
        "regularity": {
            "ES:Verbos irregulares": "irregular",
            "ES:Verbos regulares": "regular",
        },
        # 2) Prefix-based extractor → "key" row
        "paradigma": {  # = conjugation pattern
            "prefix": "ES:Verbos del paradigma ",
        },
        "endings": ["er", "ar", "ir"],
    },
}


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


def get_base_infinitive(entry: dict) -> (str, str):
    """Return a normalized base infinitive, stripping reflexive 'se' for Spanish."""
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

    parts = []
    for part in split_pron(p2):
        if part not in parts:
            parts.append(part)
    for part in split_pron(p7):
        if part not in parts:
            parts.append(part)

    return " //".join(parts) + " " if parts else None


def build_row_meta():
    """Map internal keys to (row label, mode, Kaikki tense-key)."""
    return {
        "infinitivo": {
            "label": "Infinitivo",
            "mode": "infinitivo",
            "key": None,  # from lemma
        },
        "gerundio": {
            "label": "Gerundio",
            "mode": "gerundio",
            "key": ("gerund",),
        },
        "participio": {
            "label": "Participio",
            "mode": "participio",
            "key": ("participle",),
        },
        "ind_presente": {
            "label": "Indicativo Presente",
            "mode": "indicativo",
            "key": ("indicative", "present"),
        },
        "ind_imperfecto": {
            "label": "Indicativo Pretérito Imperfecto",
            "mode": "indicativo",
            "key": ("imperfect", "indicative", "past"),
        },
        "ind_preterito_indefinido": {
            "label": "Indicativo Pretérito Indefinido",
            "mode": "indicativo",
            "key": ("indicative", "perfect", "present"),
        },
        "ind_futuro": {
            "label": "Indicativo Futuro",
            "mode": "indicativo",
            "key": ("future", "indicative"),
        },
        "ind_preterito_perfecto": {
            "label": "Indicativo Pretérito Perfecto",
            "mode": "indicativo",
            "key": ("compound", "indicative", "perfect", "present"),
        },
        "ind_pluscuamperfecto": {
            "label": "Indicativo Pretérito Pluscuamperfecto",
            "mode": "indicativo",
            "key": ("indicative", "pluperfect"),
        },
        "ind_preterito_anterior": {
            "label": "Indicativo Pretérito Anterior",
            "mode": "indicativo",
            "key": ("anterior", "archaic", "indicative", "past"),
        },
        "ind_futuro_perfecto": {
            "label": "Indicativo Futuro Perfecto",
            "mode": "indicativo",
            "key": ("compound", "future", "indicative"),
        },
        "subj_presente": {
            "label": "Subjuntivo Presente",
            "mode": "subjuntivo",
            "key": ("present", "subjunctive"),
        },
        "subj_imperfecto": {
            "label": "Subjuntivo Pretérito Imperfecto",
            "mode": "subjuntivo",
            "key": ("imperfect", "past", "subjunctive"),
        },
        "subj_futuro": {
            "label": "Subjuntivo Futuro",
            "mode": "subjuntivo",
            "key": ("archaic", "future", "subjunctive"),
        },
        "subj_preterito_perfecto": {
            "label": "Subjuntivo Pretérito Perfecto",
            "mode": "subjuntivo",
            "key": ("perfect", "present", "subjunctive"),
        },
        "subj_pluscuamperfecto": {
            "label": "Subjuntivo Pretérito Pluscuamperfecto",
            "mode": "subjuntivo",
            "key": ("pluperfect", "subjunctive"),
        },
        "subj_futuro_perfecto": {
            "label": "Subjuntivo Futuro Perfecto",
            "mode": "subjuntivo",
            "key": ("archaic", "compound", "future", "subjunctive"),
        },
        "condicional": {
            "label": "Condicional",
            "mode": "condicional",
            "key": ("conditional",),
        },
        "condicional_perfecto": {
            "label": "Condicional Perfecto",
            "mode": "condicional",
            "key": ("compound", "conditional"),
        },
        "imp_afirmativo": {
            "label": "Imperativo Afirmativo",
            "mode": "imperativo",
            "key": ("imperative", "present"),
        },
        "imp_negativo": {
            "label": "Imperativo Negativo",
            "mode": "imperativo",
            "key": None,  # special case handled in code
        },
    }


def build_header():
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


def extract_category_tags(entry: dict) -> list[str]:
    """Return normalized tags as a list."""
    lang_code = entry.get("lang_code")
    if not lang_code:
        return []

    lang_cfg = CATEGORY_CONFIG.get(lang_code)
    if not lang_cfg:
        return []

    mapping = lang_cfg.get("categories", {})
    result: list[str] = []

    for cat in entry.get("categories", []):
        if cat in mapping:
            tag = mapping[cat]
            if tag not in result:
                result.append(tag)

    return result


def extract_metadata(entry: dict) -> dict[str, list[str]]:
    """
    Read entry['categories'] and return something like:
      {
        "categories": ["tercera conjugación", "irregular", "transitivo"],
        "paradigma": ["dar"],
      }

    Rules per CATEGORY_CONFIG:
      - if config value is a dict with 'prefix' → prefix-based extractor
      - otherwise it's a simple lookup mapping: wikicat -> normalized tag
    """
    lang_code = entry.get("lang_code")
    if not lang_code:
        return {}

    lang_cfg = CATEGORY_CONFIG.get(lang_code)
    if not lang_cfg:
        return {}

    cats = entry.get("categories", []) or []
    result: dict[str, list[str]] = {}

    # add normalized base infinitive and reflexive flag
    base_infinitive, reflexive_bool = get_base_infinitive(entry)
    result["base_infinitive"] = [base_infinitive]
    result["reflexive"] = [reflexive_bool]

    for row_label, conf in lang_cfg.items():
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
        if isinstance(conf, dict):
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
            base_inf = result.get("base_infinitive")[0]
            for ending in conf:
                if base_inf.endswith(ending):
                    lst = result.setdefault(row_label, [])
                    lst.append(ending)
                    break
            continue

    return result


def build_metadata_df(entry: dict, header: list[str]) -> pl.DataFrame | None:
    """Turn extract_metadata(entry) into 1+ DataFrame rows aligned to `header`."""
    meta_map = extract_metadata(entry)
    if not meta_map:
        return None

    rows: list[list[str | None]] = []

    for row_label, values in meta_map.items():
        if not values:
            continue

        # first column: row_label; then all values; then pad to header length
        row_vals: list[str | None] = [row_label, *values]
        if len(row_vals) < len(header):
            row_vals.extend([None] * (len(header) - len(row_vals)))
        else:
            row_vals = row_vals[: len(header)]

        rows.append(row_vals)

    if not rows:
        return None

    # force a consistent UTF-8 schema for all columns + explicit row orientation
    schema = {col: pl.Utf8 for col in header}
    return pl.DataFrame(rows, schema=schema, orient="row")


def build_csv_for_entry(entry: dict, header, row_meta, row_order, output_dir: Path):
    """Build CSV file for a single verb entry."""
    forms = entry.get("forms", [])
    lemma = entry.get("word")

    # group forms by tense-key
    forms_by_key = collections.defaultdict(list)
    for f in forms:
        tk = tense_key(f["tags"])
        forms_by_key[tk].append(f)

    rows: list[dict[str, str | None]] = []

    for key in row_order:
        meta = row_meta[key]
        row = {h: None for h in header}
        row[""] = meta["label"]
        row["mode"] = meta["mode"]

        if key == "infinitivo":
            row["conjunction-1"] = lemma

        elif key == "gerundio":
            g_forms = forms_by_key.get(meta["key"], [])
            if g_forms:
                chosen = min(g_forms, key=lambda f: len(f["form"]))
                row["conjunction-1"] = chosen["form"]

        elif key == "participio":
            p_forms = forms_by_key.get(meta["key"], [])
            if p_forms:
                row["conjunction-1"] = p_forms[0]["form"]

        else:
            if key == "imp_negativo":
                tk = row_meta["subj_presente"]["key"]
            else:
                tk = meta["key"]

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

            # fill remaining slots
            for idx, flist in by_idx.items():
                if key == "imp_negativo" and idx == 1:
                    continue

                for f in flist:
                    conj = f["form"]
                    refl, verb = split_refl(conj)
                    pron = normalize_pronoun(f.get("raw_tags", []))

                    # c_conj = f"conjunction-{idx}"  # not used for Spanish but will be in other languages
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

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{lemma}.csv"

    # main conjugation table
    schema = {col: pl.Utf8 for col in header}  # schema with all UTF-8 columns
    df_conj = pl.DataFrame(rows, schema=schema, orient="row")

    # metadata row
    df_meta = build_metadata_df(entry, header)

    if df_meta is not None:
        df_meta = df_meta.cast(schema)  # ensure same schema
        df_final = pl.concat([df_conj, df_meta], how="vertical")
    else:
        df_final = df_conj

    df_final.write_csv(out_path, separator=";")
    print(f"Wrote CSV to {out_path}")


def main():
    """Main function to convert infinitive verbs JSONL into per-verb CSV files."""
    header = build_header()
    row_meta = build_row_meta()
    row_order = [
        "infinitivo",
        "gerundio",
        "participio",
        "ind_presente",
        "ind_imperfecto",
        "ind_preterito_indefinido",
        "ind_futuro",
        "ind_preterito_perfecto",
        "ind_pluscuamperfecto",
        "ind_preterito_anterior",
        "ind_futuro_perfecto",
        "subj_presente",
        "subj_imperfecto",
        "subj_futuro",
        "subj_preterito_perfecto",
        "subj_pluscuamperfecto",
        "subj_futuro_perfecto",
        "condicional",
        "condicional_perfecto",
        "imp_afirmativo",
        "imp_negativo",
    ]

    count = 0
    with INFINITIVES_JSONL.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)
            build_csv_for_entry(entry, header, row_meta, row_order, OUTPUT_DIR)

            count += 1
            if MAX_VERBS is not None and count >= MAX_VERBS:
                print(f"Stopped after {MAX_VERBS} verbs (MAX_VERBS limit).")
                break


if __name__ == "__main__":
    start = time.time()
    main()
    print(f"Completed in {time.time() - start:.2f} seconds.")
