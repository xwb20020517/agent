import argparse
import json
import re
from pathlib import Path


def natural_sort_key(path):
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def iter_input_paths(input_dir, pattern, output_path):
    input_dir = Path(input_dir)
    output_path = Path(output_path).resolve()
    paths = []

    for path in input_dir.glob(pattern):
        if not path.is_file():
            continue
        if path.resolve() == output_path:
            continue
        paths.append(path)

    return sorted(paths, key=natural_sort_key)


def merge_jsonl_files(input_paths, output_path, fail_on_duplicate=True):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen_chunk_ids = {}
    file_counts = []
    total = 0
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8", newline="\n") as out:
        for input_path in input_paths:
            count = 0
            with input_path.open("r", encoding="utf-8") as f:
                for line_number, line in enumerate(f, start=1):
                    if not line.strip():
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError(
                            f"{input_path}:{line_number} is not valid JSON: {exc}"
                        ) from exc

                    chunk_id = chunk.get("chunk_id")
                    if chunk_id:
                        first_seen = seen_chunk_ids.get(chunk_id)
                        if first_seen and fail_on_duplicate:
                            raise ValueError(
                                f"duplicate chunk_id {chunk_id!r}: "
                                f"first seen in {first_seen}, repeated in {input_path}:{line_number}"
                            )
                        seen_chunk_ids.setdefault(chunk_id, f"{input_path}:{line_number}")

                    out.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                    count += 1
                    total += 1

            file_counts.append((input_path, count))

    temp_path.replace(output_path)
    return total, file_counts


def parse_args():
    parser = argparse.ArgumentParser(description="Merge multiple chunks JSONL files into one chunks.jsonl.")
    parser.add_argument("--input-dir", default=".", help="Directory containing chunks JSONL files.")
    parser.add_argument("--pattern", default="chunks*.jsonl", help="Glob pattern for input files.")
    parser.add_argument("--output-path", default="chunks.jsonl", help="Merged output JSONL path.")
    parser.add_argument(
        "--allow-duplicate-chunk-id",
        action="store_true",
        help="Allow repeated chunk_id values instead of failing.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_path = Path(args.output_path)
    if not output_path.is_absolute():
        output_path = input_dir / output_path

    input_paths = iter_input_paths(input_dir, args.pattern, output_path)
    if not input_paths:
        raise SystemExit(f"No input files matched {input_dir / args.pattern}")

    total, file_counts = merge_jsonl_files(
        input_paths,
        output_path,
        fail_on_duplicate=not args.allow_duplicate_chunk_id,
    )

    for path, count in file_counts:
        print(f"{path.name}: {count}")
    print(f"merged {len(file_counts)} files, {total} chunks -> {output_path}")


if __name__ == "__main__":
    main()
