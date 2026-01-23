"""Module for Catalan-specific processing logic."""

from typing import Any
from src.helpers.extract_from_spec import extract_from_spec


def add_catalan_category_tags(entry: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """
    Add Catalan verb category tags (verb group and regularity) to rows.
    The info on verb-group and regularity is stored as a verb form, not in a proper category tag.
    """

    form = {"path": ["forms"]}
    cat = extract_from_spec(entry, form, [["table-tags"]])[0].split()

    verb_groups = {  # Map verb-group tags to human-readable categories
        "conjugation-1": "1st conjugation",
        "conjugation-2": "2nd conjugation",
        "conjugation-3": "3rd conjugation",
    }

    if not cat[0] in verb_groups:  # Systematic error in kaikki data - for some verbs verb-group is missing and only regularity is given
        rows.append({"key": "regularity", "mode": cat[0]})
        return

    regularity = cat[1] if len(cat) == 2 else "regular"  # Only irregular verbs have the tag --> all others are regular

    rows.append({"key": "verb-group", "mode": verb_groups[cat[0]]})
    rows.append({"key": "regularity", "mode": regularity})


def create_catalan_compound_tenses(rows: list[dict[str, Any]], reflexive_bool: bool) -> None:
    """
    The English kaikki data does not have compound tenses for Catalan - so we construct them manually.
    Data comes from the Catalan wiktionary conjugation tables, which are unfortunately not included in the kaikki data.
    """

    compound_tenses = {
        # TODO: check if to include alternative forms: e.g. "van" vs. "varen"
        "Indicatiu Perfet": ["he", "has", "ha", "hem", "heu", "han"],
        "Indicatiu Passat Perifràstic": ["vaig", "vas", "va", "vam", "vau", "van"],
        "Indicatiu Plusquamperfet": ["havia", "havies", "havia", "havíem", "havíeu", "havien"],
        "Indicatiu Passat Anterior": ["haguí", "hagueres", "hagué", "haguérem", "haguéreu", "hagueren"],
        "Indicatiu Passat Anterior Perifràstic": ["vaig haver", "vas haver", "va haver", "vam haver", "vau haver", "van haver"],
        "Indicatiu Futur Perfet": ["hauré", "hauràs", "haurà", "haurem", "haureu", "hauran"],
        "Condicional Perfet": ["hauria", "hauries", "hauria", "hauríem", "hauríeu", "haurien"],
        "Subjuntiu Passat Perifràstic": ["vagi", "vagis", "vagi", "vàgim", "vàgiu", "vagin"],
        "Subjuntiu Perfet": ["hagi", "hagis", "hagi", "hàgim", "hàgiu", "hagin"],
        "Subjuntiu Plusquamperfet": ["hagúes", "haguessis", "hagués", "haguéssim", "haguéssiu", "haguessin"],
        "Subjuntiu Passat Anterior Perifràstic": ["vagi haver", "vagis haver", "vagi haver", "vàgim haver", "vàgiu haver", "vagin haver"],
    }

    reflexive_pronouns = {
        "full": ["em ", "et ", "es ", "ens ", "us ", "es "],
        "shortened": ["m'", "t'", "s'", "ens", "us", "s'"],
    }

    base_row = next(r for r in rows if r.get("key") == "Condicional")
    participle = next(r for r in rows if r.get("key") == "Participi").get("conjunction-1")

    # Compound tense rows are fully regular, no exceptions AFAIK
    for tense, auxiliaries in compound_tenses.items():
        row = base_row.copy()
        row["key"] = tense
        row["mode"] = tense.split()[0].lower()

        for i in range(6):
            aux = auxiliaries[i]
            row[f"conjugation-{i + 1}"] = f"{aux} {participle}"

            if reflexive_bool:
                if aux.startswith("h"):
                    refl_pronoun = reflexive_pronouns["shortened"][i]
                else:
                    refl_pronoun = reflexive_pronouns["full"][i]
                row[f"refl_pronoun-{i + 1}"] = refl_pronoun

        rows.append(row)
