"""Compress raw language-extract JSONL files to .jsonl.gz."""

import gzip
from pathlib import Path

BASE_INPUT = Path("../data/language-dumps")

FILES = ["ca-extract.jsonl", "es-extract.jsonl"]


def compress_file(path: Path):
    """Compress a single file to .gz format."""
    out = path.with_suffix(path.suffix + ".gz")

    print(f"Compressing {path.name} -> {out.name}")

    with path.open("rt", encoding="utf-8") as fin, gzip.open(out, "wt", encoding="utf-8") as fout:
        for line in fin:
            fout.write(line)

    print(f"Done: {out} (compressed created)")


def main():
    """Main function to compress files."""
    for name in FILES:
        src = BASE_INPUT / name
        if not src.exists():
            print(f"Skipping {name}, file not found")
            continue
        compress_file(src)


if __name__ == "__main__":
    main()
