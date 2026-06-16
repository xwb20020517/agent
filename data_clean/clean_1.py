import json
from pathlib import Path


def collect_content(obj):
    """递归提取所有 content 字段"""
    contents = []

    if isinstance(obj, dict):
        if "content" in obj and obj["content"] is not None:
            contents.append(str(obj["content"]))

        for value in obj.values():
            contents.extend(collect_content(value))

    elif isinstance(obj, list):
        for item in obj:
            contents.extend(collect_content(item))

    return contents


def extract_page_number(discarded_blocks):
    """从 discarded_blocks 中提取 type == page_number 的 content"""
    if not isinstance(discarded_blocks, list):
        return None

    page_numbers = []

    for block in discarded_blocks:
        if not isinstance(block, dict):
            continue

        if block.get("type") == "page_number":
            contents = collect_content(block)
            page_numbers.extend(contents)

    if not page_numbers:
        return None

    return "".join(page_numbers).strip()


def is_empty(value):
    """
    判断字段是否为空。
    注意：0 不算空，因为 page_idx = 0 是合法的。
    """
    if value is None:
        return True

    if isinstance(value, str) and value.strip() == "":
        return True

    if isinstance(value, list) and len(value) == 0:
        return True

    if isinstance(value, dict) and len(value) == 0:
        return True

    return False


def clean_pdf_json(raw_data):
    """清洗原始 JSON"""
    cleaned_data = {
        "pdf_info": []
    }

    pdf_info = raw_data.get("pdf_info", [])

    for page in pdf_info:
        if not isinstance(page, dict):
            continue

        cleaned_page = {
            "page_idx": page.get("page_idx"),
            "page_number": extract_page_number(page.get("discarded_blocks", [])),
            "para_blocks": page.get("para_blocks", [])
        }

        cleaned_data["pdf_info"].append(cleaned_page)

    return cleaned_data


def validate_cleaned_data(cleaned_data):
    """
    校验清洗后的数据字段是否非空。
    返回错误列表。
    """
    errors = []

    if "pdf_info" not in cleaned_data:
        errors.append("顶层缺少 pdf_info 字段")
        return errors

    if is_empty(cleaned_data["pdf_info"]):
        errors.append("pdf_info 为空")
        return errors

    for i, page in enumerate(cleaned_data["pdf_info"]):
        if not isinstance(page, dict):
            errors.append(f"pdf_info[{i}] 不是字典对象")
            continue

        required_fields = ["page_idx", "page_number", "para_blocks"]

        for field in required_fields:
            if field not in page:
                errors.append(f"pdf_info[{i}] 缺少字段：{field}")
            elif is_empty(page[field]):
                errors.append(
                    f"pdf_info[{i}] 字段为空：{field}，page_idx={page.get('page_idx')}"
                )

    return errors


def clean_json_file(input_path, output_path, error_path=None):
    input_path = Path(input_path)
    output_path = Path(output_path)

    with input_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    cleaned_data = clean_pdf_json(raw_data)

    errors = validate_cleaned_data(cleaned_data)

    if errors:
        print("数据校验失败，发现以下问题：")
        for err in errors:
            print("-", err)

        if error_path:
            error_path = Path(error_path)
            with error_path.open("w", encoding="utf-8") as f:
                json.dump(errors, f, ensure_ascii=False, indent=2)

        raise ValueError("清洗后的 JSON 存在空字段，请先检查数据。")

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

    print(f"清洗并校验完成：{output_path}")


if __name__ == "__main__":
    clean_json_file(
        input_path="MinerU_row.json",
        output_path="cleaned_1.json",
        error_path="clean_errors.json"
    )