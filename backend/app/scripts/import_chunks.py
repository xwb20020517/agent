import argparse
import asyncio

from app.db.session import AsyncSessionLocal
from app.rag.importer import import_jsonl_dir, import_jsonl_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import manual chunks from JSONL into MySQL.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--file", default="..\data_clean\chunks.jsonl", help="Path to one JSONL chunk file.")
    target.add_argument("--dir", help="Path to a directory containing JSONL chunk files.")
    return parser.parse_args()


def print_stats(stats) -> None:
    source_files = ", ".join(sorted(stats.source_files)) or "-"
    print(f"导入文件：{stats.file_path}")
    print(f"source_file：{source_files}")
    print(f"新增 chunks：{stats.inserted}")
    print(f"更新 chunks：{stats.updated}")
    print(f"跳过 chunks：{stats.skipped}")
    print(f"失败 chunks：{stats.failed}")
    print(f"总耗时：{stats.elapsed_seconds:.2f} 秒")


async def main() -> None:
    args = parse_args()
    async with AsyncSessionLocal() as session:
        if args.file:
            print_stats(await import_jsonl_file(session, args.file))
            return
        for stats in await import_jsonl_dir(session, args.dir):
            print_stats(stats)


if __name__ == "__main__":
    asyncio.run(main())
    # uv run python -m app.scripts.import_chunks --file ..\data_clean\chunks.jsonl
