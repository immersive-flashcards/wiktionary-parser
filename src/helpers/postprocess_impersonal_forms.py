"""Limit impersonal forms for various romance languages"""

from typing import Any


def postprocess_impersonal_forms(lang_config, rows: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    """Limit impersonal forms according to the language config"""

    if entry.get("word") not in lang_config.meta_data.get("impersonal-verbs"):
        return

    for row in rows:
        # remove all other forms
        for idx in [1, 2, 4, 5, 6, 7]:
            for k in [f"conjunction-{idx}", f"pronoun-{idx}", f"negation-{idx}", f"refl_pronoun-{idx}", f"conjugation-{idx}"]:
                row.pop(k, None)

        # adjust pronoun for 3rd person singular
        if row.get("pronoun-3"):
            p = lang_config.meta_data.get("impersonal-pronoun")

            row["pronoun-3"] = None if not p else p
