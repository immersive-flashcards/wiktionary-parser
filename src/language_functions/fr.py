"""Module for French-specific processing logic."""

from typing import Any


def causes_elision(s: str, rows: list[dict[str, Any]]) -> bool:
    """Check if a conjugation causes elision (shortening of the preceeding word)"""

    # if s starts with vowel
    if s[0] in "aeioué":
        return True

    # handle 'H' - including aspirated h which doesn't cause elision
    ind_pr = next(r for r in rows if r.get("key") == "Indicatif Présent")
    if s[0] == "h" and ind_pr.get("pronoun-1") == "j’":
        return True

    return False


def create_french_negative_imperative(lang_config, rows: list[dict[str, Any]], reflexive: bool) -> None:
    """Add negative imperative forms == subjuntivo forms"""

    neg = {"long": "ne ", "short": "n'", "after": " pas "}

    try:
        row = next(r for r in rows if r.get("key") == "Impératif Présent").copy()
        row["key"] = "Impératif Négatif"

        for idx in lang_config.person_data.get("imperative-pronouns").keys():
            if causes_elision(row[f"conjugation-{idx}"], rows):
                if reflexive:
                    row[f"negation-{idx}"] = neg["long"]
                    row[f"refl_pronoun-{idx}"] = lang_config.person_data.get("reflexive-pronouns").get(idx)[-1]
                    row[f"conjugation-{idx}"] = row[f"conjugation-{idx}"].split("-")[0]
                else:
                    row[f"negation-{idx}"] = neg["short"]
            else:
                row[f"negation-{idx}"] = neg["long"]

            row[f"conjugation-{idx}"] += neg["after"]

        rows.append(row)
    except StopIteration:  # No imperative form --> no negative imperative
        pass

    try:
        row = next(r for r in rows if r.get("key") == "Impératif Passé").copy()
        row["key"] = "Impératif Passé Négatif"

        for idx in lang_config.person_data.get("imperative-pronouns").keys():
            if causes_elision(row[f"conjugation-{idx}"], rows):
                row[f"negation-{idx}"] = neg["short"]
            else:
                row[f"negation-{idx}"] = neg["long"]

            aux, part = row[f"conjugation-{idx}"].split(" ")
            row[f"conjugation-{idx}"] = aux + neg["after"] + part

        rows.append(row)
    except StopIteration:
        pass
