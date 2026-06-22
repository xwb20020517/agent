import json
import re
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from app.rag.utils import normalize_query
from app.services.llm_service import chat_completion


MAX_HYBRID_QUERIES = 5
MAX_KEYWORDS = 8
MAX_QUERY_CHARS = 300
MAX_KEYWORD_CHARS = 40


QUERY_REWRITE_SYSTEM_PROMPT = """你是车辆用户手册 RAG 系统的查询理解与改写助手。

你的任务不是回答用户问题，而是结合【历史摘要】、【最近对话】和【当前用户问题】，把当前问题转换成更适合检索车辆用户手册的查询表达。

请根据用户问题输出 JSON，包含以下字段：

{
  "original_query": "用户原始问题",
  "rewritten_query": "适合向量检索的自然语言问题",
  "keywords": ["适合关键词检索的手册术语"],
  "sub_queries": ["如果用户问题包含多个问题，则拆成多个子问题；否则为空数组"]
}

要求：

1. 不要回答问题。
2. 不要编造车辆功能、车型、页码、故障原因或解决方法。
3. 结合历史摘要和最近对话，尽量消解“它、这个、那个、这种情况、刚才说的、上面那个”等指代，让 rewritten_query 成为一个脱离上下文也能检索的独立问题。
4. 如果历史能明确当前问题指代的功能、故障现象、操作对象或场景，要写入 rewritten_query 和 keywords。
5. 如果历史不足以确定指代，只做最小改写，不要过度推断。
6. 只把口语表达转换成车辆用户手册中可能出现的专业表达。
7. keywords 只输出检索词，不输出完整句子。
8. rewritten_query 用完整自然语言问题表达，适合做向量检索。
9. 如果用户问题包含多个意图，拆成最多 3 个 sub_queries；子问题也要尽量消解历史指代。
10. 输出必须是 JSON，不要输出额外解释。
"""


class QueryRewriteResult(BaseModel):
    original_query: str
    rewritten_query: str
    keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    used_llm: bool = True

    def hybrid_queries(self) -> list[str]:
        queries: list[str] = []
        for query in [self.original_query, self.rewritten_query, *self.sub_queries]:
            cleaned = _clean_query(query)
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
        return queries[:MAX_HYBRID_QUERIES]

    def keyword_query(self) -> str:
        return " ".join(self.keywords)


def _clean_query(query: str | None) -> str:
    if not query:
        return ""
    cleaned = normalize_query(str(query))
    return cleaned[:MAX_QUERY_CHARS]


def _clean_keyword(keyword: str | None) -> str:
    if not keyword:
        return ""
    cleaned = normalize_query(str(keyword))
    if not cleaned:
        return ""
    sentence_marks = "。！？!?；;，,"
    cleaned = cleaned.strip(sentence_marks)
    if any(mark in cleaned for mark in sentence_marks):
        return ""
    return cleaned[:MAX_KEYWORD_CHARS]


def _fallback_result(user_query: str) -> QueryRewriteResult:
    cleaned = _clean_query(user_query)
    return QueryRewriteResult(
        original_query=cleaned,
        rewritten_query=cleaned,
        keywords=[],
        sub_queries=[],
        used_llm=False,
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(_strip_trailing_commas(text))
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(_strip_trailing_commas(match.group(0)))

    if not isinstance(parsed, dict):
        raise ValueError("query rewrite response must be a JSON object")
    return parsed


def _strip_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _clean_string_list(value: Any, *, max_items: int, keyword_mode: bool = False) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    for raw_item in value:
        cleaned = _clean_keyword(str(raw_item)) if keyword_mode else _clean_query(str(raw_item))
        if cleaned and cleaned not in items:
            items.append(cleaned)
        if len(items) >= max_items:
            break
    return items


def _result_from_payload(user_query: str, payload: dict[str, Any]) -> QueryRewriteResult:
    original_query = _clean_query(user_query)
    rewritten_query = _clean_query(payload.get("rewritten_query")) or original_query
    sub_queries = [
        query
        for query in _clean_string_list(payload.get("sub_queries"), max_items=3)
        if query != rewritten_query and query != original_query
    ]
    keywords = _clean_string_list(payload.get("keywords"), max_items=MAX_KEYWORDS, keyword_mode=True)

    return QueryRewriteResult(
        original_query=original_query,
        rewritten_query=rewritten_query,
        keywords=keywords,
        sub_queries=sub_queries,
        used_llm=True,
    )


def _build_rewrite_messages(user_query: str, history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    return _build_rewrite_messages_with_summary(user_query, history=history, history_summary=None)


def _build_rewrite_messages_with_summary(
    user_query: str,
    *,
    history: list[dict[str, str]] | None,
    history_summary: str | None,
) -> list[dict[str, str]]:
    summary_text = history_summary or "当前没有历史摘要。"
    history_text = "当前没有历史信息。"
    if history:
        history_lines = []
        for item in history[-6:]:
            role = item.get("role", "unknown")
            content = normalize_query(item.get("content", ""))
            if content:
                history_lines.append(f"{role}: {content[:500]}")
        if history_lines:
            history_text = "\n".join(history_lines)

    user_prompt = f"""历史摘要：
{summary_text}

最近对话：
{history_text}

用户问题：
{user_query}"""
    return [
        {"role": "system", "content": QUERY_REWRITE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


async def rewrite_query(
    user_query: str,
    *,
    history: list[dict[str, str]] | None = None,
    history_summary: str | None = None,
) -> QueryRewriteResult:
    original_query = _clean_query(user_query)
    if not original_query:
        return _fallback_result(user_query)

    try:
        raw_response = await chat_completion(
            _build_rewrite_messages_with_summary(
                original_query,
                history=history,
                history_summary=history_summary,
            )
        )
        payload = _extract_json_object(raw_response)
        result = _result_from_payload(original_query, payload)
        logger.info(
            "Query rewrite succeeded used_llm={} hybrid_queries={} keywords={}",
            result.used_llm,
            result.hybrid_queries(),
            result.keywords,
        )
        return result
    except Exception as exc:
        logger.warning("Query rewrite failed, fallback to original query: {}", exc)
        return _fallback_result(original_query)
