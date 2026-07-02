import argparse
import json
from pathlib import Path


def infer_page_number(page_idx, page_number_offset):
    """通过 page_idx 和外部传入的偏移量推断真实页码。"""
    try:
        return int(page_idx) + int(page_number_offset)
    except (TypeError, ValueError):
        return None


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


def clean_pdf_json(raw_data, page_number_offset=1):
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
            "page_number": infer_page_number(page.get("page_idx"), page_number_offset),
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


def clean_json_file(input_path, output_path, error_path=None, page_number_offset=1):
    input_path = Path(input_path)
    output_path = Path(output_path)

    with input_path.open("r", encoding="utf-8") as f:
        raw_data = json.load(f)

    cleaned_data = clean_pdf_json(raw_data, page_number_offset=page_number_offset)

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

    if error_path:
        error_path = Path(error_path)
        if error_path.exists():
            error_path.unlink()

    print(f"清洗并校验完成：{output_path}")


def parse_args():
    parser = argparse.ArgumentParser(description="Clean MinerU JSON and infer page_number from page_idx.")
    parser.add_argument("input_path", nargs="?", default="data\\夏1_180.json")
    parser.add_argument("output_path", nargs="?", default="cleaned_1.json")
    parser.add_argument("--error-path", default="clean_errors.json")
    parser.add_argument(
        "--page-number-offset",
        type=int,
        default=1,
        help="Real page number = page_idx + page_number_offset.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    clean_json_file(
        input_path=args.input_path,
        output_path=args.output_path,
        error_path=args.error_path,
        page_number_offset=args.page_number_offset,
    )
    # python .\clean_1.py data\汉301_412.json cleaned_1.json --page-number-offset 301
