"""Module for Spanish-specific processing logic."""

from typing import Any


def merge_tu_vos_if_equal(row: dict[str, Any]):
    """Join tú and vos forms if they are the same"""
    if row.get("conjugation-2") is not None and row.get("conjugation-2") == row.get("conjugation-7"):
        row["pronoun-2"] += "//" + row["pronoun-7"]

        # remove vos form columns
        for k in ["conjunction-7", "pronoun-7", "negation-7", "refl_pronoun-7", "conjugation-7"]:
            row.pop(k, None)


def force_merge_vos_subjunctive(row: dict[str, Any]):
    """Join tú and vos forms if for the Subjuntivo Presente - its voseo form is archaic and shouldn't be used"""
    if row.get("key") == "Subjuntivo Presente" and row.get("conjugation-7"):
        row["pronoun-2"] += "//" + row["pronoun-7"]

        # remove vos form columns
        for k in ["conjunction-7", "pronoun-7", "negation-7", "refl_pronoun-7", "conjugation-7"]:
            row.pop(k, None)


def create_spanish_negative_imperative(rows: list[dict[str, Any]]):
    """Add negative imperative forms == subjuntivo forms"""
    row = next(r for r in rows if r.get("key") == "Subjuntivo Presente").copy()
    imp_afirm = next(r for r in rows if r.get("key") == "Imperativo Afirmativo")

    try:
        # remove 1st person sing. form columns
        for k in ["conjunction-1", "pronoun-1", "negation-1", "refl_pronoun-1", "conjugation-1"]:
            row.pop(k, None)

        row["key"] = "Imperativo Negativo"
        row["mode"] = "imperativo"
        for i in range(2, 7):
            row[f"pronoun-{i}"] = imp_afirm[f"pronoun-{i}"]
            row[f"negation-{i}"] = "no "

        rows.append(row)
    except KeyError:
        pass
