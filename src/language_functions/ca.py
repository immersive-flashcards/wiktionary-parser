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
