from app.core.config import settings
from app.rag.retriever import RetrievedChunk
from app.rag.utils import content_preview
from app.schemas.rag import RAGSource


NO_ANSWER = "根据当前用户手册资料，未检索到相关内容，无法确定答案。"


def format_page_range(start: str | None, end: str | None) -> str:
    if start and end and start != end:
        return f"{start}-{end}"
    return start or end or "未知"


def build_context(chunks: list[RetrievedChunk], max_chars: int | None = None) -> str:
    limit = max_chars or settings.RAG_CONTEXT_MAX_CHARS
    blocks: list[str] = []
    total = 0
    for index, chunk in enumerate(chunks, start=1):
        block = (
            f"[资料{index}]\n"
            f"来源文件：{chunk.source_file}\n"
            f"章节：{chunk.section_title or '未标注'}\n"
            f"页码：{format_page_range(chunk.page_number_start, chunk.page_number_end)}\n"
            f"内容：{chunk.content}\n"
        )
        if total + len(block) > limit:
            remain = limit - total
            if remain > 120:
                blocks.append(block[:remain])
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks).strip()


def build_rag_prompt(query: str, chunks: list[RetrievedChunk]) -> list[dict[str, str]]:
    context = build_context(chunks)
    prompt = f"""你是一个汽车用户手册智能问答助手。

你只能根据【用户手册资料】回答问题。
如果资料中没有明确答案，请回答“根据当前用户手册资料，无法确定”。
不要编造不存在的功能、按钮、参数、配置、故障原因或操作步骤。
如果涉及驾驶安全、维修、充电、故障处理，请提醒用户注意安全，并建议以车辆实际提示和官方售后为准。
回答应简洁、清楚，优先给出操作步骤。

【用户手册资料】
{context}

【用户问题】
{query}

请根据用户手册资料回答："""
    return [{"role": "user", "content": prompt}]


def build_sources(chunks: list[RetrievedChunk]) -> list[RAGSource]:
    return [
        RAGSource(
            chunk_id=chunk.chunk_id,
            source_file=chunk.source_file,
            section_title=chunk.section_title,
            page_number_start=chunk.page_number_start,
            page_number_end=chunk.page_number_end,
            score=chunk.score,
            content_preview=content_preview(chunk.content),
        )
        for chunk in chunks
    ]
