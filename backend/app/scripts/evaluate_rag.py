import argparse
import asyncio
import json
import re
import string
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from app.core.config import BASE_DIR, settings
from app.rag.prompt_builder import build_rag_prompt
from app.rag.retriever import RetrievedChunk, retrieve_chunks
from app.services.llm_service import stream_chat_completion


DEFAULT_EVAL_FILE = BASE_DIR.parent / "data_clean" / "eval.jsonl"
DEFAULT_OUTPUT_DIR = BASE_DIR.parent / "data_clean" / "eval_runs"


@dataclass
class CaseMetrics:
    case_id: str
    question: str
    source_file: str | None
    gold_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    gold_pages: list[str]
    retrieved_pages: list[str]
    chunk_hit: bool
    chunk_recall: float
    chunk_precision: float
    mrr: float
    page_hit: bool
    page_recall: float
    answer: str | None
    gold_answer: str | None
    answer_exact_match: bool | None
    answer_char_f1: float | None
    answer_rouge_l: float | None
    latency_ms: int
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the RAG pipeline with a JSONL golden set.")
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE, help="JSONL file with golden cases.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for result files.")
    parser.add_argument("--top-k", type=int, default=settings.RAG_TOP_K, help="Retriever top_k.")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases.")
    parser.add_argument(
        "--no-source-filter",
        action="store_true",
        help="Do not constrain retrieval with each case's source_file.",
    )
    parser.add_argument(
        "--generate-answers",
        action="store_true",
        help="Call the configured LLM and evaluate generated answers. Retrieval-only by default.",
    )
    parser.add_argument("--verbose", action="store_true", help="Keep backend logs enabled during evaluation.")
    return parser.parse_args()


def read_eval_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_no, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                cases.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
    return cases


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    lowered = text.lower()
    punctuation = string.punctuation + "，。！？；：、“”‘’（）【】《》—…￥·"
    return re.sub(r"\s+", "", lowered.translate(str.maketrans("", "", punctuation)))


def char_f1(prediction: str | None, reference: str | None) -> float:
    pred_chars = list(normalize_text(prediction))
    ref_chars = list(normalize_text(reference))
    if not pred_chars and not ref_chars:
        return 1.0
    if not pred_chars or not ref_chars:
        return 0.0

    ref_counts: dict[str, int] = {}
    for char in ref_chars:
        ref_counts[char] = ref_counts.get(char, 0) + 1

    overlap = 0
    for char in pred_chars:
        if ref_counts.get(char, 0) > 0:
            overlap += 1
            ref_counts[char] -= 1

    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_chars)
    recall = overlap / len(ref_chars)
    return 2 * precision * recall / (precision + recall)


def rouge_l_f1(prediction: str | None, reference: str | None) -> float:
    pred = list(normalize_text(prediction))
    ref = list(normalize_text(reference))
    if not pred and not ref:
        return 1.0
    if not pred or not ref:
        return 0.0

    previous = [0] * (len(ref) + 1)
    for pred_char in pred:
        current = [0]
        for index, ref_char in enumerate(ref, start=1):
            if pred_char == ref_char:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current

    lcs = previous[-1]
    if lcs == 0:
        return 0.0
    precision = lcs / len(pred)
    recall = lcs / len(ref)
    return 2 * precision * recall / (precision + recall)


def pages_for_chunk(chunk: RetrievedChunk) -> list[str]:
    pages: list[str] = []
    for page in (chunk.page_number_start, chunk.page_number_end):
        if page and page not in pages:
            pages.append(str(page))
    return pages


def retrieval_metrics(
    *,
    gold_chunk_ids: list[str],
    retrieved_chunk_ids: list[str],
    gold_pages: list[str],
    retrieved_pages: list[str],
) -> tuple[bool, float, float, float, bool, float]:
    gold_chunk_set = set(gold_chunk_ids)
    retrieved_chunk_set = set(retrieved_chunk_ids)
    chunk_overlap = gold_chunk_set & retrieved_chunk_set
    chunk_hit = bool(chunk_overlap)
    chunk_recall = len(chunk_overlap) / len(gold_chunk_set) if gold_chunk_set else 0.0
    chunk_precision = len(chunk_overlap) / len(retrieved_chunk_set) if retrieved_chunk_set else 0.0

    reciprocal_rank = 0.0
    for rank, chunk_id in enumerate(retrieved_chunk_ids, start=1):
        if chunk_id in gold_chunk_set:
            reciprocal_rank = 1 / rank
            break

    gold_page_set = set(gold_pages)
    retrieved_page_set = set(retrieved_pages)
    page_overlap = gold_page_set & retrieved_page_set
    page_hit = bool(page_overlap)
    page_recall = len(page_overlap) / len(gold_page_set) if gold_page_set else 0.0
    return chunk_hit, chunk_recall, chunk_precision, reciprocal_rank, page_hit, page_recall


async def generate_answer(question: str, chunks: list[RetrievedChunk]) -> str:
    answer = ""
    async for token in stream_chat_completion(build_rag_prompt(question, chunks)):
        answer += token
    return answer


async def evaluate_case(case: dict[str, Any], *, top_k: int, use_source_filter: bool, generate: bool) -> CaseMetrics:
    started_at = perf_counter()
    case_id = str(case.get("case_id") or "")
    question = str(case["question"])
    source_file = str(case["source_file"]) if case.get("source_file") else None
    gold_chunk_ids = [str(item) for item in case.get("gold_chunk_ids", [])]
    gold_pages = [str(item) for item in case.get("gold_pages", [])]
    gold_answer = str(case.get("gold_answer") or "")

    try:
        chunks = await retrieve_chunks(
            question,
            source_file=source_file if use_source_filter else None,
            top_k=top_k,
            redis=None,
        )
        retrieved_chunk_ids = [chunk.chunk_id for chunk in chunks]
        retrieved_pages: list[str] = []
        for chunk in chunks:
            for page in pages_for_chunk(chunk):
                if page not in retrieved_pages:
                    retrieved_pages.append(page)

        chunk_hit, chunk_recall, chunk_precision, mrr, page_hit, page_recall = retrieval_metrics(
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            gold_pages=gold_pages,
            retrieved_pages=retrieved_pages,
        )

        answer = await generate_answer(question, chunks) if generate and chunks else None
        answer_exact_match = None
        answer_f1 = None
        answer_rouge_l = None
        if generate:
            answer_exact_match = normalize_text(answer) == normalize_text(gold_answer)
            answer_f1 = char_f1(answer, gold_answer)
            answer_rouge_l = rouge_l_f1(answer, gold_answer)

        return CaseMetrics(
            case_id=case_id,
            question=question,
            source_file=source_file,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            gold_pages=gold_pages,
            retrieved_pages=retrieved_pages,
            chunk_hit=chunk_hit,
            chunk_recall=chunk_recall,
            chunk_precision=chunk_precision,
            mrr=mrr,
            page_hit=page_hit,
            page_recall=page_recall,
            answer=answer,
            gold_answer=gold_answer if generate else None,
            answer_exact_match=answer_exact_match,
            answer_char_f1=answer_f1,
            answer_rouge_l=answer_rouge_l,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
    except Exception as exc:
        return CaseMetrics(
            case_id=case_id,
            question=question,
            source_file=source_file,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=[],
            gold_pages=gold_pages,
            retrieved_pages=[],
            chunk_hit=False,
            chunk_recall=0.0,
            chunk_precision=0.0,
            mrr=0.0,
            page_hit=False,
            page_recall=0.0,
            answer=None,
            gold_answer=gold_answer if generate else None,
            answer_exact_match=None,
            answer_char_f1=None,
            answer_rouge_l=None,
            latency_ms=int((perf_counter() - started_at) * 1000),
            error=str(exc),
        )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(results: list[CaseMetrics], *, top_k: int, generate: bool) -> dict[str, Any]:
    successful = [item for item in results if item.error is None]
    summary: dict[str, Any] = {
        "total": len(results),
        "successful": len(successful),
        "failed": len(results) - len(successful),
        "top_k": top_k,
        "retrieval": {
            "chunk_hit_rate": mean([1.0 if item.chunk_hit else 0.0 for item in successful]),
            "chunk_recall": mean([item.chunk_recall for item in successful]),
            "chunk_precision": mean([item.chunk_precision for item in successful]),
            "mrr": mean([item.mrr for item in successful]),
            "page_hit_rate": mean([1.0 if item.page_hit else 0.0 for item in successful]),
            "page_recall": mean([item.page_recall for item in successful]),
        },
        "latency_ms": {
            "avg": mean([float(item.latency_ms) for item in successful]),
            "max": max([item.latency_ms for item in successful], default=0),
        },
    }
    if generate:
        answer_items = [item for item in successful if item.answer_char_f1 is not None]
        summary["generation"] = {
            "exact_match": mean([1.0 if item.answer_exact_match else 0.0 for item in answer_items]),
            "char_f1": mean([float(item.answer_char_f1) for item in answer_items]),
            "rouge_l": mean([float(item.answer_rouge_l) for item in answer_items]),
        }
    return summary


async def main() -> None:
    args = parse_args()
    if not args.verbose:
        logger.remove()

    cases = read_eval_cases(args.eval_file)
    if args.limit is not None:
        cases = cases[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mode = "end_to_end" if args.generate_answers else "retrieval"
    result_file = args.output_dir / f"{mode}_top{args.top_k}_results.jsonl"
    summary_file = args.output_dir / f"{mode}_top{args.top_k}_summary.json"

    results: list[CaseMetrics] = []
    with result_file.open("w", encoding="utf-8") as output:
        for index, case in enumerate(cases, start=1):
            metrics = await evaluate_case(
                case,
                top_k=args.top_k,
                use_source_filter=not args.no_source_filter,
                generate=args.generate_answers,
            )
            results.append(metrics)
            output.write(json.dumps(asdict(metrics), ensure_ascii=False) + "\n")
            status = "ok" if metrics.error is None else "failed"
            print(
                f"[{index}/{len(cases)}] {metrics.case_id} {status} "
                f"chunk_hit={metrics.chunk_hit} page_hit={metrics.page_hit} latency_ms={metrics.latency_ms}"
            )

    summary = summarize(results, top_k=args.top_k, generate=args.generate_answers)
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"results: {result_file}")
    print(f"summary: {summary_file}")


if __name__ == "__main__":
    asyncio.run(main())
