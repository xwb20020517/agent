import argparse
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path


TEXT_BLOCK_TYPES = {
    "title",
    "text",
    "table_caption",
    "table_footnote",
    "image_caption",
    "image_footnote",
}


class TableHTMLParser(HTMLParser):
    """Extract table rows from a small HTML table fragment."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._current_row = None
        self._current_cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = {
                "text": [],
                "rowspan": _safe_int(attrs.get("rowspan"), 1),
                "colspan": _safe_int(attrs.get("colspan"), 1),
            }

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell["text"].append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._current_cell is not None:
            text = normalize_text("".join(self._current_cell["text"]))
            self._current_row.append(
                {
                    "text": text,
                    "rowspan": self._current_cell["rowspan"],
                    "colspan": self._current_cell["colspan"],
                }
            )
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None


def _safe_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_text(value):
    """Normalize OCR text while preserving Chinese line-wrap continuity."""
    if value is None:
        return ""

    text = html.unescape(str(value))
    text = text.replace("\u3000", " ")
    text = re.sub(r"[\t\r\n]+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def join_fragments(fragments, separator=""):
    cleaned = [normalize_text(fragment) for fragment in fragments]
    cleaned = [fragment for fragment in cleaned if fragment]
    return separator.join(cleaned).strip()


def collect_line_text(block):
    """Collect text from MinerU lines/spans without layout metadata."""
    if not isinstance(block, dict):
        return ""

    lines = []
    for line in block.get("lines", []):
        if not isinstance(line, dict):
            continue
        fragments = []
        for span in line.get("spans", []):
            if not isinstance(span, dict):
                continue
            if "content" in span:
                fragments.append(span.get("content"))
        line_text = join_fragments(fragments)
        if line_text:
            lines.append(line_text)

    return join_fragments(lines)


def collect_text(obj):
    """Recursively collect meaningful content text from nested blocks."""
    texts = []

    if isinstance(obj, dict):
        line_text = collect_line_text(obj)
        if line_text:
            texts.append(line_text)
        elif obj.get("type") in TEXT_BLOCK_TYPES and "content" in obj:
            content = normalize_text(obj.get("content"))
            if content:
                texts.append(content)

        for key, value in obj.items():
            if key in {"bbox", "angle", "score", "index", "html", "lines"}:
                continue
            texts.extend(collect_text(value))

    elif isinstance(obj, list):
        for item in obj:
            texts.extend(collect_text(item))

    return texts


def collect_html_tables(obj):
    html_tables = []

    if isinstance(obj, dict):
        if obj.get("type") == "table" and obj.get("html"):
            html_tables.append(obj["html"])
        for value in obj.values():
            html_tables.extend(collect_html_tables(value))
    elif isinstance(obj, list):
        for item in obj:
            html_tables.extend(collect_html_tables(item))

    return html_tables


def collect_image_paths(obj):
    image_paths = []

    if isinstance(obj, dict):
        if obj.get("image_path"):
            image_ref = {
                "image_path": obj.get("image_path"),
            }
            if obj.get("bbox") is not None:
                image_ref["bbox"] = obj.get("bbox")
            if obj.get("type") is not None:
                image_ref["type"] = obj.get("type")
            image_paths.append(image_ref)

        for value in obj.values():
            image_paths.extend(collect_image_paths(value))

    elif isinstance(obj, list):
        for item in obj:
            image_paths.extend(collect_image_paths(item))

    return image_paths


def collect_typed_text(block, target_type):
    texts = []
    if isinstance(block, dict):
        if block.get("type") == target_type:
            text = join_fragments(collect_text(block), separator=" ")
            if text:
                texts.append(text)
        for value in block.values():
            texts.extend(collect_typed_text(value, target_type))
    elif isinstance(block, list):
        for item in block:
            texts.extend(collect_typed_text(item, target_type))
    return texts


def is_image_related_type(block_type):
    return isinstance(block_type, str) and block_type.startswith("image")


def contains_image_related_block(obj):
    if isinstance(obj, dict):
        if is_image_related_type(obj.get("type")):
            return True
        return any(contains_image_related_block(value) for value in obj.values())
    if isinstance(obj, list):
        return any(contains_image_related_block(item) for item in obj)
    return False


def collect_content_values(obj):
    contents = []
    if isinstance(obj, dict):
        if obj.get("content") is not None:
            content = normalize_text(obj.get("content"))
            if content:
                contents.append(content)
        for value in obj.values():
            contents.extend(collect_content_values(value))
    elif isinstance(obj, list):
        for item in obj:
            contents.extend(collect_content_values(item))
    return contents


def build_image_manifest(raw_data):
    manifest = {
        "description": "Images are excluded from text RAG and kept here for future multimodal retrieval.",
        "images": [],
    }

    for page in raw_data.get("pdf_info", []):
        if not isinstance(page, dict):
            continue

        page_idx = page.get("page_idx")
        page_number = page.get("page_number")

        for para_idx, block in enumerate(page.get("para_blocks", [])):
            if not isinstance(block, dict):
                continue

            if not contains_image_related_block(block):
                continue

            image_refs = collect_image_paths(block)
            captions = collect_typed_text(block, "image_caption")
            footnotes = collect_typed_text(block, "image_footnote")
            content_descriptions = collect_content_values(block)

            entry = {
                "page_idx": page_idx,
                "page_number": page_number,
                "para_idx": para_idx,
                "block_idx": block.get("index"),
                "source_block_type": block.get("type"),
                "bbox": block.get("bbox"),
                "image_refs": image_refs,
            }

            caption = join_fragments(captions, separator=" ")
            footnote = join_fragments(footnotes, separator=" ")

            if caption:
                entry["caption"] = caption
            if footnote:
                entry["footnote"] = footnote
            if content_descriptions:
                entry["content_descriptions"] = content_descriptions

            manifest["images"].append(entry)

    return manifest


def expand_rowspans(raw_rows):
    """Expand simple rowspan/colspan table cells into a rectangular grid."""
    rows = []
    pending = {}

    for raw_row in raw_rows:
        row = []
        col = 0

        def flush_pending():
            nonlocal col
            while col in pending:
                text, remaining = pending[col]
                row.append(text)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, remaining - 1)
                col += 1

        flush_pending()
        for cell in raw_row:
            flush_pending()
            text = cell["text"]
            rowspan = cell["rowspan"]
            colspan = cell["colspan"]

            for offset in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col + offset] = (text, rowspan - 1)
            col += colspan

        flush_pending()
        rows.append(row)

    width = max((len(row) for row in rows), default=0)
    if width == 0:
        return []

    return [row + [""] * (width - len(row)) for row in rows]


def fill_empty_context_columns(rows, context_columns=(0,)):
    """Forward-fill leading context columns that carry row grouping semantics."""
    if not rows:
        return rows

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    filled_rows = [header]
    last_values = {}

    for row in normalized_rows[1:]:
        filled_row = list(row)
        for col in context_columns:
            if col >= len(filled_row):
                continue
            if normalize_text(filled_row[col]):
                last_values[col] = filled_row[col]
            elif col in last_values:
                filled_row[col] = last_values[col]
        filled_rows.append(filled_row)

    return filled_rows


def parse_table_html(table_html):
    parser = TableHTMLParser()
    parser.feed(table_html)
    rows = expand_rowspans(parser.rows)
    return fill_empty_context_columns(rows)


def rows_to_records(rows):
    if len(rows) < 2:
        return []

    header = [normalize_text(cell) for cell in rows[0]]
    records = []
    for row in rows[1:]:
        record = {}
        for col, key in enumerate(header):
            if not key:
                continue
            value = normalize_text(row[col] if col < len(row) else "")
            if value:
                record[key] = value
        if record:
            records.append(record)
    return records


def records_to_text(records):
    lines = []
    for i, record in enumerate(records, start=1):
        parts = [f"{key}：{value}" for key, value in record.items()]
        if parts:
            lines.append(f"第{i}条：\n" + "\n".join(parts))
    return "\n\n".join(lines)


def markdown_escape_cell(value):
    return normalize_text(value).replace("|", "\\|")


def rows_to_markdown(rows):
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    body = normalized_rows[1:]

    lines = [
        "| " + " | ".join(markdown_escape_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(markdown_escape_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def clean_text_block(block):
    content = collect_line_text(block)
    if not content:
        return None

    cleaned = {
        "type": block.get("type", "text"),
        "content": content,
    }

    if "level" in block:
        cleaned["level"] = block.get("level")
    if "index" in block:
        cleaned["index"] = block.get("index")

    return cleaned


def clean_list_block(block):
    items = []
    for child in block.get("blocks", []):
        item = join_fragments(collect_text(child))
        if item:
            items.append(item)

    if not items:
        return None

    marker = "1." if block.get("sub_type") == "ordered" else "-"
    if marker == "1.":
        content = "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))
    else:
        content = "\n".join(f"- {item}" for item in items)

    cleaned = {
        "type": "list",
        "content": content,
        "items": items,
    }
    if "index" in block:
        cleaned["index"] = block.get("index")

    return cleaned


def clean_table_block(block):
    captions = []
    footnotes = []
    html_fragments = []

    for child in block.get("blocks", []):
        child_type = child.get("type") if isinstance(child, dict) else None
        child_text = join_fragments(collect_text(child))
        if child_type == "table_caption" and child_text:
            captions.append(child_text)
        elif child_type == "table_footnote" and child_text:
            footnotes.append(child_text)
        html_fragments.extend(collect_html_tables(child))

    tables = []
    for fragment in html_fragments:
        rows = parse_table_html(fragment)
        if rows:
            tables.append(rows)

    caption = join_fragments(captions, separator=" ")

    row_records = []
    for rows in tables:
        row_records.extend(rows_to_records(rows))

    content_parts = []
    if caption:
        content_parts.append(f"表格：{caption}")

    records_text = records_to_text(row_records)
    if records_text:
        content_parts.append(records_text)

    footnote = join_fragments(footnotes, separator=" ")
    if footnote:
        content_parts.append(footnote)

    content = "\n\n".join(content_parts).strip()
    if not content:
        fallback = join_fragments(collect_text(block), separator=" ")
        if not fallback:
            return None
        content = fallback

    cleaned = {
        "block_idx": block.get("index"),
        "type": "table",
        "content": content,
    }
    if caption:
        cleaned["caption"] = caption
    if tables:
        markdown_tables = [rows_to_markdown(rows) for rows in tables]
        cleaned["markdown"] = "\n\n".join(table for table in markdown_tables if table)
    if row_records:
        cleaned["rows"] = row_records

    return cleaned


def clean_image_block(block):
    captions = []
    footnotes = []
    text_parts = []

    for child in block.get("blocks", []):
        child_type = child.get("type") if isinstance(child, dict) else None
        child_text = join_fragments(collect_text(child))
        if not child_text:
            continue
        if child_type == "image_caption":
            captions.append(child_text)
        elif child_type == "image_footnote":
            footnotes.append(child_text)
        else:
            text_parts.append(child_text)

    caption = join_fragments(captions, separator=" ")
    footnote = join_fragments(footnotes, separator=" ")
    content = "\n".join(part for part in [caption, *text_parts, footnote] if part).strip()
    if not content:
        return None

    cleaned = {
        "type": "image",
        "content": content,
    }
    if caption:
        cleaned["caption"] = caption
    if "index" in block:
        cleaned["index"] = block.get("index")

    return cleaned


def clean_unknown_block(block):
    content = join_fragments(collect_text(block), separator=" ")
    if not content:
        return None

    cleaned = {
        "type": block.get("type", "unknown"),
        "content": content,
    }
    if "index" in block:
        cleaned["index"] = block.get("index")
    return cleaned


def clean_para_block(block):
    if not isinstance(block, dict):
        return None

    block_type = block.get("type")
    if block_type in {"title", "text"}:
        return clean_text_block(block)
    if block_type == "list":
        return clean_list_block(block)
    if block_type == "table":
        return clean_table_block(block)
    if block_type == "image":
        return None
    return clean_unknown_block(block)


def clean_pdf_json(raw_data):
    cleaned_data = {"pdf_info": []}

    for page in raw_data.get("pdf_info", []):
        if not isinstance(page, dict):
            continue

        cleaned_blocks = []
        for block in page.get("para_blocks", []):
            cleaned_block = clean_para_block(block)
            if cleaned_block and cleaned_block.get("content"):
                cleaned_blocks.append(cleaned_block)

        page_text = "\n\n".join(block["content"] for block in cleaned_blocks)
        cleaned_page = {
            "page_idx": page.get("page_idx"),
            "page_number": page.get("page_number"),
            "para_blocks": cleaned_blocks,
            "page_content": page_text,
        }
        cleaned_data["pdf_info"].append(cleaned_page)

    return cleaned_data


def validate_cleaned_data(cleaned_data):
    errors = []
    if not isinstance(cleaned_data.get("pdf_info"), list):
        return ["top-level pdf_info must be a list"]

    for page_idx, page in enumerate(cleaned_data["pdf_info"]):
        if not isinstance(page, dict):
            errors.append(f"pdf_info[{page_idx}] is not an object")
            continue
        if "para_blocks" not in page or not isinstance(page["para_blocks"], list):
            errors.append(f"pdf_info[{page_idx}].para_blocks must be a list")
            continue
        for block_idx, block in enumerate(page["para_blocks"]):
            if not isinstance(block, dict):
                errors.append(f"pdf_info[{page_idx}].para_blocks[{block_idx}] is not an object")
                continue
            if not normalize_text(block.get("content")):
                errors.append(f"pdf_info[{page_idx}].para_blocks[{block_idx}] has empty content")
    return errors


def clean_json_file(input_path, output_path, error_path=None, image_manifest_path=None):
    input_path = Path(input_path)
    output_path = Path(output_path)

    with input_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    cleaned_data = clean_pdf_json(raw_data)
    image_manifest = build_image_manifest(raw_data)
    errors = validate_cleaned_data(cleaned_data)

    if errors:
        if error_path:
            error_path = Path(error_path)
            with error_path.open("w", encoding="utf-8") as f:
                json.dump(errors, f, ensure_ascii=False, indent=2)
        raise ValueError("cleaned JSON validation failed; see error output for details")

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    if image_manifest_path:
        image_manifest_path = Path(image_manifest_path)
        with image_manifest_path.open("w", encoding="utf-8") as f:
            json.dump(image_manifest, f, ensure_ascii=False, indent=2)

    print(f"cleaned para_blocks written to: {output_path}")
    if image_manifest_path:
        print(f"image manifest written to: {image_manifest_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Clean MinerU para_blocks for RAG.")
    parser.add_argument("input_path", nargs="?", default="cleaned_1.json")
    parser.add_argument("output_path", nargs="?", default="cleaned_2.json")
    parser.add_argument("--error-path", default="clean_2_errors.json")
    parser.add_argument("--image-manifest-path", default="image_manifest.json")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    clean_json_file(
        input_path=args.input_path,
        output_path=args.output_path,
        error_path=args.error_path,
        image_manifest_path=args.image_manifest_path,
    )
