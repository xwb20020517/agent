import argparse
import asyncio
import json
import re
import string
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from loguru import logger

from app.core.config import BASE_DIR, settings
from app.rag.prompt_builder import build_rag_prompt
from app.rag.retriever import expand_chunk_contexts, retrieve_chunks, retrieve_rewritten_query_seeds
from app.rag.retriever_types import RetrievedChunk
from app.services.llm_service import stream_chat_completion
from app.services.query_rewrite_service import rewrite_query


DEFAULT_EVAL_FILE = BASE_DIR.parent / "data_clean" / "eval.jsonl"
DEFAULT_OUTPUT_DIR = BASE_DIR.parent / "data_clean" / "eval_runs"


@dataclass
class CaseMetrics:
    case_id: str
    question: str
    rewritten_query: str | None
    source_file: str | None
    gold_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    retrieved_context_chunk_ids: list[list[str]]
    gold_pages: list[str]
    retrieved_pages: list[str]
    chunk_hit: bool
    chunk_recall: float
    chunk_precision: float
    mrr: float
    page_hit: bool
    page_recall: float
    context_recall: float
    context_precision: float
    context_relevance_scores: list[float]
    answer: str | None
    gold_answer: str | None
    answer_exact_match: bool | None
    answer_char_f1: float | None
    answer_rouge_l: float | None
    judge_answer_correctness: float | None
    judge_faithfulness: float | None
    judge_evidence_coverage: float | None
    judge_context_relevance: float | None
    judge_hallucination: bool | None
    judge_reason: str | None
    judge_raw_response: str | None
    judge_error: str | None
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
    parser.add_argument(
        "--llm-judge",
        action="store_true",
        help="Generate answers and use the configured LLM as a judge for correctness and faithfulness.",
    )
    parser.add_argument(
        "--context-relevance-threshold",
        type=float,
        default=0.35,
        help="Minimum gold-reference coverage for a retrieved chunk to count as context-relevant.",
    )
    parser.add_argument(
        "--no-query-rewrite",
        action="store_true",
        help="Use the legacy single-query retrieve_chunks path instead of rewritten multi-route retrieval.",
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


def char_recall(prediction: str | None, reference: str | None) -> float:
    pred_chars = list(normalize_text(prediction))
    ref_chars = list(normalize_text(reference))
    if not pred_chars and not ref_chars:
        return 1.0
    if not pred_chars or not ref_chars:
        return 0.0

    pred_counts: dict[str, int] = {}
    for char in pred_chars:
        pred_counts[char] = pred_counts.get(char, 0) + 1

    overlap = 0
    for char in ref_chars:
        if pred_counts.get(char, 0) > 0:
            overlap += 1
            pred_counts[char] -= 1
    return overlap / len(ref_chars)


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


def context_metrics(
    *,
    gold_reference: str,
    chunks: list[RetrievedChunk],
    relevance_threshold: float,
) -> tuple[float, float, list[float]]:
    if not gold_reference or not chunks:
        return 0.0, 0.0, []

    retrieved_context = "\n".join(chunk.content for chunk in chunks)
    context_recall = char_recall(retrieved_context, gold_reference)

    relevance_scores = [char_recall(chunk.content, gold_reference) for chunk in chunks]
    relevant_seen = 0
    precision_sum = 0.0
    for rank, score in enumerate(relevance_scores, start=1):
        if score >= relevance_threshold:
            relevant_seen += 1
            precision_sum += relevant_seen / rank

    context_precision = precision_sum / relevant_seen if relevant_seen else 0.0
    return context_recall, context_precision, relevance_scores


def format_retrieved_context(chunks: list[RetrievedChunk], max_chars: int | None = None) -> str:
    limit = max_chars or settings.RAG_CONTEXT_MAX_CHARS
    blocks: list[str] = []
    total = 0
    for index, chunk in enumerate(chunks, start=1):
        page = "-".join(
            page for page in [chunk.page_number_start, chunk.page_number_end] if page
        ) or "unknown"
        block = (
            f"[Context {index}]\n"
            f"chunk_id: {chunk.chunk_id}\n"
            f"source_file: {chunk.source_file}\n"
            f"page: {page}\n"
            f"content: {chunk.content}\n"
        )
        if total + len(block) > limit:
            remain = limit - total
            if remain > 120:
                blocks.append(block[:remain])
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def build_judge_prompt(
    *,
    question: str,
    gold_answer: str,
    gold_evidence: str,
    retrieved_context: str,
    answer: str,
) -> list[dict[str, str]]:
    prompt = f"""你是一个严格的 RAG 评估裁判。请基于给定问题、标准答案、标准证据、检索上下文和模型答案进行评分。

评分必须客观，不要因为答案措辞不同就扣分；只要语义正确且被证据支持即可。

请只输出一个 JSON 对象，不要输出 Markdown，不要输出解释性前缀。

JSON 格式：
{{
  "answer_correctness": 5,
  "faithfulness": 5,
  "evidence_coverage": 5,
  "context_relevance": 5,
  "hallucination": false,
  "reason": "一句话说明主要依据"
}}

评分标准：
- answer_correctness：模型答案和标准答案的语义一致程度。5 表示完全正确，0 表示完全错误。
- faithfulness：模型答案是否完全被检索上下文支持。5 表示全部可由上下文支持，0 表示主要内容无依据。
- evidence_coverage：检索上下文是否覆盖回答问题所需的标准证据信息。5 表示充分覆盖，0 表示没有覆盖。
- context_relevance：检索上下文和问题的相关性。5 表示高度相关，0 表示无关。
- hallucination：模型答案是否包含检索上下文或标准证据无法支持的关键事实。

【问题】
{question}

【标准答案】
{gold_answer}

【标准证据】
{gold_evidence}

【检索上下文】
{retrieved_context}

【模型答案】
{answer}
"""
    return [{"role": "user", "content": prompt}]


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("judge response does not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


def clamp_score(value: Any) -> float:
    score = float(value)
    return max(0.0, min(5.0, score))


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    raise ValueError(f"cannot parse boolean value: {value!r}")


async def run_llm_judge(
    *,
    question: str,
    gold_answer: str,
    gold_evidence: str,
    chunks: list[RetrievedChunk],
    answer: str,
) -> tuple[dict[str, Any] | None, str, str | None]:
    raw_response = ""
    retrieved_context = format_retrieved_context(chunks)
    messages = build_judge_prompt(
        question=question,
        gold_answer=gold_answer,
        gold_evidence=gold_evidence,
        retrieved_context=retrieved_context,
        answer=answer,
    )
    try:
        async for token in stream_chat_completion(messages):
            raw_response += token
        parsed = extract_json_object(raw_response)
        result = {
            "answer_correctness": clamp_score(parsed["answer_correctness"]),
            "faithfulness": clamp_score(parsed["faithfulness"]),
            "evidence_coverage": clamp_score(parsed["evidence_coverage"]),
            "context_relevance": clamp_score(parsed["context_relevance"]),
            "hallucination": parse_bool(parsed["hallucination"]),
            "reason": str(parsed.get("reason") or ""),
        }
        return result, raw_response, None
    except Exception as exc:
        return None, raw_response, str(exc)


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


async def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    rewritten_query: str | None = None,
) -> str:
    answer = ""
    async for token in stream_chat_completion(
        build_rag_prompt(question, chunks, rewritten_query=rewritten_query)
    ):
        answer += token
    return answer


async def retrieve_for_evaluation(
    question: str,
    *,
    source_file: str | None,
    top_k: int,
    use_query_rewrite: bool,
) -> tuple[list[RetrievedChunk], str | None]:
    if not use_query_rewrite:
        chunks = await retrieve_chunks(
            question,
            source_file=source_file,
            top_k=top_k,
            redis=None,
        )
        return chunks, None

    rewrite = await rewrite_query(question)
    seeds = await retrieve_rewritten_query_seeds(
        rewrite,
        source_file=source_file,
        top_k=top_k,
        redis=None,
    )
    return expand_chunk_contexts(seeds), rewrite.rewritten_query


async def evaluate_case(
    case: dict[str, Any],
    *,
    top_k: int,
    use_source_filter: bool,
    generate: bool,
    llm_judge: bool,
    use_query_rewrite: bool,
    context_relevance_threshold: float,
) -> CaseMetrics:
    started_at = perf_counter()
    case_id = str(case.get("case_id") or "")
    question = str(case["question"])
    source_file = str(case["source_file"]) if case.get("source_file") else None
    gold_chunk_ids = [str(item) for item in case.get("gold_chunk_ids", [])]
    gold_pages = [str(item) for item in case.get("gold_pages", [])]
    gold_answer = str(case.get("gold_answer") or "")
    gold_evidence = str(case.get("gold_evidence") or "")
    gold_reference = gold_evidence or gold_answer

    try:
        chunks, rewritten_query = await retrieve_for_evaluation(
            question,
            source_file=source_file if use_source_filter else None,
            top_k=top_k,
            use_query_rewrite=use_query_rewrite,
        )
        retrieved_chunk_ids = [chunk.chunk_id for chunk in chunks]
        retrieved_context_chunk_ids = [
            list(chunk.context_chunk_ids or (chunk.chunk_id,))
            for chunk in chunks
        ]
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
        context_recall, context_precision, context_relevance_scores = context_metrics(
            gold_reference=gold_reference,
            chunks=chunks,
            relevance_threshold=context_relevance_threshold,
        )

        answer = (
            await generate_answer(question, chunks, rewritten_query=rewritten_query)
            if (generate or llm_judge) and chunks
            else None
        )
        answer_exact_match = None
        answer_f1 = None
        answer_rouge_l = None
        if generate or llm_judge:
            answer_exact_match = normalize_text(answer) == normalize_text(gold_answer)
            answer_f1 = char_f1(answer, gold_answer)
            answer_rouge_l = rouge_l_f1(answer, gold_answer)

        judge_result = None
        judge_raw_response = None
        judge_error = None
        if llm_judge and answer:
            judge_result, judge_raw_response, judge_error = await run_llm_judge(
                question=question,
                gold_answer=gold_answer,
                gold_evidence=gold_evidence,
                chunks=chunks,
                answer=answer,
            )

        return CaseMetrics(
            case_id=case_id,
            question=question,
            rewritten_query=rewritten_query,
            source_file=source_file,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=retrieved_chunk_ids,
            retrieved_context_chunk_ids=retrieved_context_chunk_ids,
            gold_pages=gold_pages,
            retrieved_pages=retrieved_pages,
            chunk_hit=chunk_hit,
            chunk_recall=chunk_recall,
            chunk_precision=chunk_precision,
            mrr=mrr,
            page_hit=page_hit,
            page_recall=page_recall,
            context_recall=context_recall,
            context_precision=context_precision,
            context_relevance_scores=context_relevance_scores,
            answer=answer,
            gold_answer=gold_answer if generate or llm_judge else None,
            answer_exact_match=answer_exact_match,
            answer_char_f1=answer_f1,
            answer_rouge_l=answer_rouge_l,
            judge_answer_correctness=judge_result["answer_correctness"] if judge_result else None,
            judge_faithfulness=judge_result["faithfulness"] if judge_result else None,
            judge_evidence_coverage=judge_result["evidence_coverage"] if judge_result else None,
            judge_context_relevance=judge_result["context_relevance"] if judge_result else None,
            judge_hallucination=judge_result["hallucination"] if judge_result else None,
            judge_reason=judge_result["reason"] if judge_result else None,
            judge_raw_response=judge_raw_response,
            judge_error=judge_error,
            latency_ms=int((perf_counter() - started_at) * 1000),
        )
    except Exception as exc:
        return CaseMetrics(
            case_id=case_id,
            question=question,
            rewritten_query=None,
            source_file=source_file,
            gold_chunk_ids=gold_chunk_ids,
            retrieved_chunk_ids=[],
            retrieved_context_chunk_ids=[],
            gold_pages=gold_pages,
            retrieved_pages=[],
            chunk_hit=False,
            chunk_recall=0.0,
            chunk_precision=0.0,
            mrr=0.0,
            page_hit=False,
            page_recall=0.0,
            context_recall=0.0,
            context_precision=0.0,
            context_relevance_scores=[],
            answer=None,
            gold_answer=gold_answer if generate or llm_judge else None,
            answer_exact_match=None,
            answer_char_f1=None,
            answer_rouge_l=None,
            judge_answer_correctness=None,
            judge_faithfulness=None,
            judge_evidence_coverage=None,
            judge_context_relevance=None,
            judge_hallucination=None,
            judge_reason=None,
            judge_raw_response=None,
            judge_error=None,
            latency_ms=int((perf_counter() - started_at) * 1000),
            error=str(exc),
        )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(
    results: list[CaseMetrics],
    *,
    top_k: int,
    generate: bool,
    llm_judge: bool,
    use_query_rewrite: bool,
) -> dict[str, Any]:
    successful = [item for item in results if item.error is None]
    failed = [item for item in results if item.error is not None]
    summary: dict[str, Any] = {
        "total": len(results),
        "successful": len(successful),
        "failed": len(failed),
        "top_k": top_k,
        "use_query_rewrite": use_query_rewrite,
        "final_seed_top_k": settings.RAG_FINAL_SEED_TOP_K if use_query_rewrite else top_k,
        "retrieval": {
            "chunk_hit_rate": mean([1.0 if item.chunk_hit else 0.0 for item in successful]),
            "chunk_recall": mean([item.chunk_recall for item in successful]),
            "chunk_precision": mean([item.chunk_precision for item in successful]),
            "mrr": mean([item.mrr for item in successful]),
            "page_hit_rate": mean([1.0 if item.page_hit else 0.0 for item in successful]),
            "page_recall": mean([item.page_recall for item in successful]),
            "context_recall": mean([item.context_recall for item in successful]),
            "context_precision": mean([item.context_precision for item in successful]),
        },
        "latency_ms": {
            "avg": mean([float(item.latency_ms) for item in successful]),
            "max": max([item.latency_ms for item in successful], default=0),
        },
    }
    if failed:
        error_counts = Counter(str(item.error) for item in failed)
        summary["failure_errors"] = dict(error_counts.most_common(5))
        summary["failed_examples"] = [
            {
                "case_id": item.case_id,
                "error": item.error,
            }
            for item in failed[:5]
        ]
    if generate or llm_judge:
        answer_items = [item for item in successful if item.answer_char_f1 is not None]
        summary["generation"] = {
            "exact_match": mean([1.0 if item.answer_exact_match else 0.0 for item in answer_items]),
            "char_f1": mean([float(item.answer_char_f1) for item in answer_items]),
            "rouge_l": mean([float(item.answer_rouge_l) for item in answer_items]),
        }
    if llm_judge:
        judge_items = [item for item in successful if item.judge_answer_correctness is not None]
        summary["llm_judge"] = {
            "answer_correctness": mean([float(item.judge_answer_correctness) for item in judge_items]),
            "faithfulness": mean([float(item.judge_faithfulness) for item in judge_items]),
            "evidence_coverage": mean([float(item.judge_evidence_coverage) for item in judge_items]),
            "context_relevance": mean([float(item.judge_context_relevance) for item in judge_items]),
            "hallucination_rate": mean([1.0 if item.judge_hallucination else 0.0 for item in judge_items]),
            "judge_successful": len(judge_items),
            "judge_failed": len(successful) - len(judge_items),
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
    mode = "llm_judge" if args.llm_judge else "end_to_end" if args.generate_answers else "retrieval"
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
                llm_judge=args.llm_judge,
                use_query_rewrite=not args.no_query_rewrite,
                context_relevance_threshold=args.context_relevance_threshold,
            )
            results.append(metrics)
            output.write(json.dumps(asdict(metrics), ensure_ascii=False) + "\n")
            status = "ok" if metrics.error is None else "failed"
            print(
                f"[{index}/{len(cases)}] {metrics.case_id} {status} "
                f"chunk_hit={metrics.chunk_hit} page_hit={metrics.page_hit} latency_ms={metrics.latency_ms}"
            )

    summary = summarize(
        results,
        top_k=args.top_k,
        generate=args.generate_answers,
        llm_judge=args.llm_judge,
        use_query_rewrite=not args.no_query_rewrite,
    )
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"results: {result_file}")
    print(f"summary: {summary_file}")


if __name__ == "__main__":
    asyncio.run(main())
# uv run python -m app.scripts.evaluate_rag --top-k 5 --llm-judge
