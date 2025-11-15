import json
from pathlib import Path

INPUT_FILE = Path("es-extract.jsonl")  # your big Kaikki file
OUTPUT_FILE = Path("aburrirse.jsonl")  # filtered output

TARGET = "aburrirse"


def is_aburrirse(entry: dict) -> bool:
    """
    Return True if this Kaikki entry is for 'aburrirse'.
    We check both 'word' and 'lemma' to be safe.
    """
    if entry.get("word") == TARGET:
        return True
    if entry.get("lemma") == TARGET:
        return True
    # Some entries might have headword info in 'forms' only,
    # but for now this is usually enough.
    return False


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

            if is_aburrirse(entry):
                fout.write(json.dumps(entry, ensure_ascii=False) + "\n")
                kept += 1

    print(f"Processed {seen_lines} lines, kept {kept} for '{TARGET}'.")
    print(f"Written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
