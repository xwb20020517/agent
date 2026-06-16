import argparse
import json
import re
from pathlib import Path


MIN_CHARS = 80
MAX_CHARS = 800


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def text_len(value):
    return len(re.sub(r"\s+", "", normalize_text(value)))


def make_metadata(chunk):
    return {
        "source_file": chunk["source_file"],
        "page_idx_start": chunk["page_idx_start"],
        "page_idx_end": chunk["page_idx_end"],
        "page_number_start": chunk["page_number_start"],
        "page_number_end": chunk["page_number_end"],
        "chunk_type": chunk["chunk_type"],
        "section_title": chunk["section_title"],
    }


def make_chunk(
    source_file,
    page_idx_start,
    page_idx_end,
    page_number_start,
    page_number_end,
    chunk_type,
    section_title,
    content,
    extra=None,
):
    chunk = {
        "source_file": source_file,
        "page_idx_start": page_idx_start,
        "page_idx_end": page_idx_end,
        "page_number_start": page_number_start,
        "page_number_end": page_number_end,
        "chunk_type": chunk_type,
        "section_title": section_title,
        "content": normalize_text(content),
    }
    if extra:
        chunk.update(extra)
    chunk["metadata"] = make_metadata(chunk)
    return chunk


def block_id(block):
    return block.get("block_idx", block.get("index"))


def is_title_only_chunk(chunk):
    content_blocks = chunk.get("_content_blocks", [])
    return (
        chunk.get("chunk_type") == "text"
        and bool(content_blocks)
        and all(block_type == "title" for block_type, _ in content_blocks)
    )


def flush_text_chunk(chunks, current, source_file):
    if not current:
        return None

    content = "\n\n".join(part for part in current["parts"] if normalize_text(part))
    if normalize_text(content):
        chunks.append(
            make_chunk(
                source_file=source_file,
                page_idx_start=current["page_idx_start"],
                page_idx_end=current["page_idx_end"],
                page_number_start=current["page_number_start"],
                page_number_end=current["page_number_end"],
                chunk_type="text",
                section_title=current["section_title"],
                content=content,
                extra={"_content_blocks": list(current["content_blocks"])},
            )
        )
    return None


def start_text_chunk(title_block, page, source_file):
    title = normalize_text(title_block.get("content"))
    return {
        "section_title": title,
        "parts": [title],
        "content_blocks": [("title", title)],
        "page_idx_start": page.get("page_idx"),
        "page_idx_end": page.get("page_idx"),
        "page_number_start": page.get("page_number"),
        "page_number_end": page.get("page_number"),
    }


def append_to_text_chunk(current, block, page):
    if current is None:
        current = {
            "section_title": "",
            "parts": [],
            "content_blocks": [],
            "page_idx_start": page.get("page_idx"),
            "page_idx_end": page.get("page_idx"),
            "page_number_start": page.get("page_number"),
            "page_number_end": page.get("page_number"),
        }

    content = normalize_text(block.get("content"))
    if content:
        current["parts"].append(content)
        current["content_blocks"].append((block.get("type"), content))

    current["page_idx_end"] = page.get("page_idx")
    current["page_number_end"] = page.get("page_number")
    return current


def table_record_to_text(record, row_number):
    lines = [f"第{row_number}条："]
    for key, value in record.items():
        value = normalize_text(value)
        if value:
            lines.append(f"{key}：{value}")
    return "\n".join(lines)


def table_records_content(caption, records, start_number=1):
    parts = []
    if caption:
        parts.append(f"表格：{caption}")
    for offset, record in enumerate(records):
        parts.append(table_record_to_text(record, start_number + offset))
    return "\n\n".join(parts)


def table_records_to_markdown(records):
    if not records:
        return ""
    headers = list(records[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for record in records:
        cells = [normalize_text(record.get(header, "")).replace("|", "\\|") for header in headers]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def make_table_chunks(block, page, source_file, section_title):
    caption = normalize_text(block.get("caption"))
    rows = block.get("rows") if isinstance(block.get("rows"), list) else []

    base_extra = {
        "block_idx": block.get("block_idx"),
        "caption": caption,
    }

    content = normalize_text(block.get("content"))
    if not rows or text_len(content) <= MAX_CHARS:
        extra = dict(base_extra)
        if block.get("markdown"):
            extra["markdown"] = block.get("markdown")
        if rows:
            extra["rows"] = rows
        return [
            make_chunk(
                source_file=source_file,
                page_idx_start=page.get("page_idx"),
                page_idx_end=page.get("page_idx"),
                page_number_start=page.get("page_number"),
                page_number_end=page.get("page_number"),
                chunk_type="table",
                section_title=section_title,
                content=content,
                extra=extra,
            )
        ]

    chunks = []
    batch = []
    batch_start = 1

    for i, row in enumerate(rows, start=1):
        candidate = batch + [row]
        candidate_content = table_records_content(caption, candidate, batch_start)
        if batch and text_len(candidate_content) > MAX_CHARS:
            extra = dict(base_extra)
            extra["rows"] = batch
            extra["markdown"] = table_records_to_markdown(batch)
            chunks.append(
                make_chunk(
                    source_file=source_file,
                    page_idx_start=page.get("page_idx"),
                    page_idx_end=page.get("page_idx"),
                    page_number_start=page.get("page_number"),
                    page_number_end=page.get("page_number"),
                    chunk_type="table",
                    section_title=section_title,
                    content=table_records_content(caption, batch, batch_start),
                    extra=extra,
                )
            )
            batch = [row]
            batch_start = i
        else:
            batch = candidate

    if batch:
        extra = dict(base_extra)
        extra["rows"] = batch
        extra["markdown"] = table_records_to_markdown(batch)
        chunks.append(
            make_chunk(
                source_file=source_file,
                page_idx_start=page.get("page_idx"),
                page_idx_end=page.get("page_idx"),
                page_number_start=page.get("page_number"),
                page_number_end=page.get("page_number"),
                chunk_type="table",
                section_title=section_title,
                content=table_records_content(caption, batch, batch_start),
                extra=extra,
            )
        )

    return chunks


def build_structural_chunks(cleaned_data, source_file):
    chunks = []
    current_text = None
    current_title = ""

    for page in cleaned_data.get("pdf_info", []):
        if not isinstance(page, dict):
            continue

        for block in page.get("para_blocks", []):
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "title":
                current_text = flush_text_chunk(chunks, current_text, source_file)
                current_text = start_text_chunk(block, page, source_file)
                current_title = current_text["section_title"]
            elif block_type in {"text", "list"}:
                current_text = append_to_text_chunk(current_text, block, page)
            elif block_type == "table":
                current_text = flush_text_chunk(chunks, current_text, source_file)
                chunks.extend(make_table_chunks(block, page, source_file, current_title))
                current_text = None

    flush_text_chunk(chunks, current_text, source_file)
    return chunks


def split_by_separator(text, separator):
    parts = [part.strip() for part in text.split(separator) if part.strip()]
    chunks = []
    current = []

    for part in parts:
        candidate = separator.join(current + [part]) if current else part
        if current and text_len(candidate) > MAX_CHARS:
            chunks.append(separator.join(current))
            current = [part]
        else:
            current.append(part)

    if current:
        chunks.append(separator.join(current))
    return chunks


def hard_split(text):
    pieces = []
    start = 0
    while start < len(text):
        pieces.append(text[start : start + MAX_CHARS])
        start += MAX_CHARS
    return pieces


def recursive_split_text(text):
    text = normalize_text(text)
    if text_len(text) <= MAX_CHARS:
        return [text]

    for separator in ["\n\n", "\n", "。", "；", "，", " "]:
        parts = split_by_separator(text, separator)
        if len(parts) == 1:
            continue

        results = []
        for part in parts:
            if separator in {"。", "；", "，"} and not part.endswith(separator):
                part = part + separator
            if text_len(part) > MAX_CHARS:
                results.extend(recursive_split_text(part))
            else:
                results.append(part)
        return [part for part in results if normalize_text(part)]

    return hard_split(text)


def merge_small_title_only_chunks(chunks):
    merged = []
    i = 0
    changed = False
    while i < len(chunks):
        chunk = chunks[i]
        if (
            is_title_only_chunk(chunk)
            and text_len(chunk["content"]) < MIN_CHARS
            and i + 1 < len(chunks)
            and chunks[i + 1].get("chunk_type") != "table"
        ):
            next_chunk = chunks[i + 1]
            section_title = " / ".join(
                part
                for part in [chunk.get("section_title"), next_chunk.get("section_title")]
                if normalize_text(part)
            )
            combined = dict(next_chunk)
            combined["page_idx_start"] = chunk["page_idx_start"]
            combined["page_number_start"] = chunk["page_number_start"]
            combined["section_title"] = section_title or next_chunk.get("section_title")
            combined["content"] = normalize_text(chunk["content"] + "\n\n" + next_chunk["content"])
            combined["_content_blocks"] = chunk.get("_content_blocks", []) + next_chunk.get("_content_blocks", [])
            combined["metadata"] = make_metadata(combined)
            merged.append(combined)
            changed = True
            i += 2
        else:
            merged.append(chunk)
            i += 1
    return merged, changed


def apply_text_length_rules(chunks):
    while True:
        chunks, changed = merge_small_title_only_chunks(chunks)
        if not changed:
            break

    final_chunks = []

    for chunk in chunks:
        if chunk.get("chunk_type") == "table":
            final_chunks.append(chunk)
            continue

        if text_len(chunk["content"]) <= MAX_CHARS:
            final_chunks.append(chunk)
            continue

        for part in recursive_split_text(chunk["content"]):
            split_chunk = dict(chunk)
            split_chunk["content"] = part
            split_chunk.pop("_content_blocks", None)
            split_chunk["metadata"] = make_metadata(split_chunk)
            final_chunks.append(split_chunk)

    return final_chunks


def cleanup_internal_fields(chunks):
    cleaned = []
    for chunk in chunks:
        chunk = dict(chunk)
        chunk.pop("_content_blocks", None)
        chunk["metadata"] = make_metadata(chunk)
        cleaned.append(chunk)
    return cleaned


def assign_chunk_ids(chunks, source_file):
    source_id = Path(source_file).stem or "source"
    for i, chunk in enumerate(chunks, start=1):
        page_idx = chunk.get("page_idx_start")
        page_part = f"p{page_idx}" if page_idx is not None else "punknown"
        chunk["chunk_id"] = f"{source_id}_{page_part}_c{i:03d}"
        ordered = {
            "chunk_id": chunk["chunk_id"],
            "source_file": chunk["source_file"],
            "page_idx_start": chunk["page_idx_start"],
            "page_idx_end": chunk["page_idx_end"],
            "page_number_start": chunk["page_number_start"],
            "page_number_end": chunk["page_number_end"],
            "chunk_type": chunk["chunk_type"],
            "section_title": chunk["section_title"],
            "content": chunk["content"],
            "metadata": chunk["metadata"],
        }
        for key, value in chunk.items():
            if key not in ordered and key != "chunk_id":
                ordered[key] = value
        yield ordered


def build_chunks(cleaned_data, source_file):
    chunks = build_structural_chunks(cleaned_data, source_file)
    chunks = apply_text_length_rules(chunks)
    chunks = cleanup_internal_fields(chunks)
    return list(assign_chunk_ids(chunks, source_file))


def write_jsonl(chunks, output_path):
    output_path = Path(output_path)
    with output_path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def convert_file(input_path, output_path, source_file=None):
    input_path = Path(input_path)
    with input_path.open("r", encoding="utf-8") as f:
        cleaned_data = json.load(f)

    source_file = source_file or input_path.with_suffix(".pdf").name
    chunks = build_chunks(cleaned_data, source_file)
    write_jsonl(chunks, output_path)
    print(f"chunks written to: {output_path}")
    print(f"chunk count: {len(chunks)}")
    return chunks


def parse_args():
    parser = argparse.ArgumentParser(description="Convert cleaned_2.json into RAG chunks.jsonl.")
    parser.add_argument("input_path", nargs="?", default="cleaned_2.json")
    parser.add_argument("output_path", nargs="?", default="chunks.jsonl")
    parser.add_argument("--source-file", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    convert_file(args.input_path, args.output_path, source_file=args.source_file)
