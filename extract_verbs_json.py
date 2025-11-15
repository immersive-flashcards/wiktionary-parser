import json
from pathlib import Path

# ---- CONFIGURATION ----
INPUT_FILE = Path("es-extract.jsonl")        # big Kaikki dump
OUTPUT_FILE = Path("spanish-verbs.jsonl")    # filtered output
TARGET_LANG = "Español"                      # language name as in Kaikki, e.g. "Spanish", "French", "Italian"


def is_target_language_verb(entry: dict) -> bool:
    """
    Return True if this Kaikki entry is an infinitive verb in the target language.
    We use:
      - entry["lang"] for the language
      - entry["pos"] == "verb" to select only headword verb entries
    """
    if entry.get("lang") != TARGET_LANG:
        return False

    if entry.get("pos") != "verb":
        return False

    if "ES:Verbos" not in entry.get("categories"):
        return False

    return True


def main():
    kept = 0
    seen_lines = 0

    with INPUT_FILE.open("r", encoding="utf-8") as fin, \
            OUTPUT_FILE.open("w", encoding="utf-8") as fout:

        for line in fin:
            seen_lines += 1
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)

            if is_target_language_verb(entry):
                # Keep the entry as-is; you'll process structure later
                fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
                kept += 1

    print(f"Processed {seen_lines} lines.")
    print(f"Kept {kept} verb entries for language '{TARGET_LANG}'.")
    print(f"Written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
