import json
import collections
import pandas as pd
from pathlib import Path


INPUT_JSON = Path("aburrirse.jsonl")   # your pretty-printed Kaikki/Wiktextract file
OUTPUT_CSV = Path("aburrirse_from_kaikki.csv")


def tense_key(tags):
    """Return a normalized key for tense/mood/aspect ignoring person/number."""
    ignore = {
        "first-person", "second-person", "third-person",
        "singular", "plural", "vos-form",
        "impersonal", "informal", "formal",
        "masculine", "feminine", "masculine-form", "feminine-form",
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
    """
    Split off a leading reflexive pronoun (me/te/se/nos/os) when it's a separate token.
    For forms like 'abúrrete', we do NOT try to split (returns (None, full_form)).
    """
    refls = {"me", "te", "se", "nos", "os"}
    parts = form_str.split()
    if parts and parts[0] in refls:
        return parts[0] + " ", " ".join(parts[1:])
    return None, form_str


def normalize_pronoun(raw_tags):
    """
    Normalize raw_tags into something like 'él //ella //usted '.
    We do NOT invent missing pieces (e.g. no 'ellas' if it's not there).
    """
    if not raw_tags:
        return None
    s = raw_tags[0]
    s = s.replace("que ", "")       # remove 'que ' from subjunctive labels
    s = s.strip()
    s = s.replace(", ", " //")      # commas → double slashes
    return s + " "                  # trailing space for consistency


def build_row_meta():
    """
    Map internal keys to (row label, mode, Kaikki tense-key).
    Only rows that can be directly mapped from Kaikki are filled;
    Imperativo Negativo is kept but left empty.
    """
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
            "key": None,  # we do NOT derive this (would require extra logic)
        },
    }


def main():
    # --- Load Kaikki entry (pretty-printed JSON) ---
    with INPUT_JSON.open("r", encoding="utf-8") as f:
        entry = json.load(f)

    forms = entry.get("forms", [])
    lemma = entry.get("word")

    # --- Group forms by tense-key ---
    forms_by_key = collections.defaultdict(list)
    for f in forms:
        tk = tense_key(f["tags"])
        forms_by_key[tk].append(f)

    # --- Prepare CSV header ---
    header = ["", "mode"]
    for i in range(1, 8):
        header.extend([
            f"conjunction-{i}",
            f"pronoun-{i}",
            f"negation-{i}",
            f"refl_pronoun-{i}",
            f"conjugation-{i}",
        ])

    # --- Define row order (similar to your sample) ---
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

    rows = []

    for key in row_order:
        meta = row_meta[key]
        row = {h: None for h in header}
        row[""] = meta["label"]
        row["mode"] = meta["mode"]

        # Non-finite
        if key == "infinitivo":
            row["conjunction-1"] = lemma

        elif key == "gerundio":
            g_forms = forms_by_key.get(meta["key"], [])
            if g_forms:
                # choose the shortest gerund (likely the simple one)
                chosen = min(g_forms, key=lambda f: len(f["form"]))
                row["conjunction-1"] = chosen["form"]

        elif key == "participio":
            p_forms = forms_by_key.get(meta["key"], [])
            if p_forms:
                row["conjunction-1"] = p_forms[0]["form"]

        elif key == "imp_negativo":
            # We consciously leave Imperativo Negativo empty:
            # Kaikki doesn't give explicit negative imperative forms like "no te aburras".
            pass

        else:
            # Finite tenses
            tk = meta["key"]
            f_list = forms_by_key.get(tk, [])
            for f in f_list:
                idx = person_index(f["tags"])
                if not idx:
                    continue

                conj = f["form"]
                refl, verb = split_refl(conj)
                pron = normalize_pronoun(f.get("raw_tags", []))

                c_conj = f"conjunction-{idx}"
                c_pron = f"pronoun-{idx}"
                c_neg = f"negation-{idx}"
                c_refl = f"refl_pronoun-{idx}"
                c_verb = f"conjugation-{idx}"

                # Only fill if still empty (avoid blindly overwriting in case of duplicates)
                if pron and row.get(c_pron) is None:
                    row[c_pron] = pron
                if refl and row.get(c_refl) is None:
                    row[c_refl] = refl
                if row.get(c_verb) is None:
                    row[c_verb] = verb

        rows.append(row)

    df = pd.DataFrame(rows, columns=header)
    df.to_csv(OUTPUT_CSV, index=False, sep=";")
    print(f"Wrote CSV to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
