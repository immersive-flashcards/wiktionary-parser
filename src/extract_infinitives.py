"""Extract infinitive verbs from language dumps for specified languages."""

import json
from pathlib import Path

BASE_INPUT = Path("../data/language-dumps")
BASE_OUTPUT = Path("../data/language-verb-dumps")

LANG_CONFIGS = {
    "ca": {
        "lang": "Catalan",
        "detector": "forms_infinitive_lemma",
    },
    "es": {
        "lang": "Español",
        "detector": "category_contains",
        "category": "ES:Verbos",
    },
}


def is_infinitive_verb(entry: dict, cfg: dict) -> bool:
    """Determine if the entry is an infinitive verb based on the configuration."""
    if entry.get("lang") != cfg["lang"]:
        return False
    if entry.get("pos") != "verb":
        return False

    detector = cfg["detector"]

    if detector == "forms_infinitive_lemma":
        lemma = entry.get("word")
        for f in entry.get("forms", []):
            if f.get("form") == lemma and "infinitive" in f.get("tags", []):
                return True
        return False

    if detector == "category_contains":
        return cfg["category"] in entry.get("categories", [])

    return False


def process_language(key: str, cfg: dict):
    """Process a single language to extract infinitive verbs."""
    # Clean predictable filenames
    input_file = BASE_INPUT / f"{key}-extract.jsonl"
    output_file = BASE_OUTPUT / f"{key}-infinitives.jsonl"

    output_file.parent.mkdir(parents=True, exist_ok=True)

    kept = 0
    seen = 0

    with input_file.open("r", encoding="utf-8") as fin, output_file.open("w", encoding="utf-8") as fout:
        for line in fin:
            seen += 1
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)

            if is_infinitive_verb(entry, cfg):
                fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
                kept += 1

    print(f"[{key}] {kept}/{seen} kept for {cfg['lang']}")


def main():
    """Main function to process all languages."""
    for key, cfg in LANG_CONFIGS.items():
        process_language(key, cfg)


if __name__ == "__main__":
    main()
