"""Compress raw language-extract JSONL files to .jsonl.zst."""

from pathlib import Path
import zstandard as zstd

BASE_INPUT = Path("../data/verb-dumps")
COMPRESSION_LEVEL = 19
CHUNK_SIZE = 1024 * 1024  # 1 MiB


def compress_file(path: Path):
    """Compress a single .jsonl file to .jsonl.zst."""
    out = path.with_suffix(path.suffix + ".zst")

    if out.exists():
        print(f"Skipping {path.name}, compressed file already exists")
        return

    print(f"Compressing {path.name} -> {out.name}")

    cctx = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)

    with path.open("rb") as fin, out.open("wb") as fout:
        with cctx.stream_writer(fout) as zf:
            while True:
                chunk = fin.read(CHUNK_SIZE)
                if not chunk:
                    break
                zf.write(chunk)

    print(f"Done: {out} (compressed created)")


def main():
    if not BASE_INPUT.exists():
        raise FileNotFoundError(f"Input directory not found: {BASE_INPUT}")

    jsonl_files = sorted(BASE_INPUT.glob("*.jsonl"))

    if not jsonl_files:
        print("No .jsonl files found")
        return

    for path in jsonl_files:
        compress_file(path)


if __name__ == "__main__":
    main()
