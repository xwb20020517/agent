# 车型用户手册 RAG 智能问答系统需求文档

## 1. 项目背景

当前项目是一个基于 FastAPI 的车型用户手册智能问答系统。

目前项目已经完成：

1. FastAPI 后端基础框架。
2. MySQL 数据库连接。
3. Redis 服务连接。
4. 用户注册、登录、退出。
5. JWT 鉴权。
6. 会话创建、查询、删除、重命名。
7. 消息保存。
8. 前后端基础联调。
9. 普通模型会话能力。

现在需要在现有后端中加入 RAG 模块，将系统从普通聊天系统升级为：

```text
车型用户手册 RAG 智能问答系统
```

新增 RAG 后，系统不再保留普通聊天能力。用户在聊天窗口中提出的所有问题，都必须先检索车型用户手册，再调用大模型生成答案。

也就是说，最终问答链路是：

```text
用户提问
→ 保存用户问题
→ 检索车型用户手册 chunk
→ 构建 RAG 上下文
→ 调用大模型生成答案
→ 保存 assistant 回答
→ 返回答案和引用来源
```

---

## 2. 当前数据状态

当前阶段不需要重新做 PDF 解析，也不需要重新做数据清洗。

PDF 用户手册已经完成清洗和切分，最终数据为 JSONL 格式，每一行是一个 chunk。

每一行 JSONL 的基本格式如下：

```json
{
  "chunk_id": "xia_p12_c003",
  "source_file": "xia.pdf",
  "page_idx_start": 12,
  "page_idx_end": 13,
  "page_number_start": "10",
  "page_number_end": "11",
  "chunk_type": "text",
  "section_title": "车辆启动",
  "content": "车辆启动。启动车辆前请确认钥匙在车内……",
  "metadata": {
    "source_file": "xia.pdf",
    "page_idx_start": 12,
    "page_idx_end": 13,
    "page_number_start": "10",
    "page_number_end": "11",
    "chunk_type": "text",
    "section_title": "车辆启动"
  }
}
```

字段说明：

1. `chunk_id`：每个 chunk 的唯一 ID。
2. `source_file`：来源 PDF 文件名，用于区分车型手册。
3. `page_idx_start`：PDF 内部开始页索引。
4. `page_idx_end`：PDF 内部结束页索引。
5. `page_number_start`：用户手册中显示的开始页码。
6. `page_number_end`：用户手册中显示的结束页码。
7. `chunk_type`：chunk 类型，例如 text、table。
8. `section_title`：章节标题。
9. `content`：实际用于检索和回答的正文内容。
10. `metadata`：用于保存来源信息，后续返回引用来源时使用。

---

## 3. 本阶段目标

本阶段目标是在现有后端中加入完整的基础 RAG 能力。

必须实现：

1. JSONL chunk 文件导入。
2. chunk 内容写入 MySQL。
3. chunk 文本向量化。
4. 向量写入向量数据库。
5. 用户提问时进行向量检索。
6. 支持按 `source_file` 限定车型手册检索。
7. 检索结果构建 RAG 上下文。
8. 调用大模型生成基于手册内容的回答。
9. 返回答案和引用来源。
10. 用户问题和 assistant 回答保存到 messages 表。
11. 每次 RAG 检索和问答过程保存到 rag_query_logs 表。
12. 前端聊天页面正常显示回答和引用来源。
13. 所有聊天请求都走 RAG，不保留普通聊天模式。

暂不实现：

1. 在线 PDF 上传。
2. 在线 PDF 解析。
3. OCR 图片识别。
4. 多模态 RAG。
5. Agent。
6. 工具调用。
7. 复杂 Query Rewrite。
8. RAG 自动评估。
9. 用户私有知识库。
10. 多租户知识库隔离。

---

## 4. 技术栈要求

### 4.1 现有技术栈

继续使用当前项目技术栈：

```text
FastAPI
SQLAlchemy Async
MySQL
Redis
Pydantic v2
uv
JWT
前端
异步模型调用
```

### 4.2 新增技术栈

新增：

```text
Qdrant：向量数据库
Embedding 服务：OpenAI-compatible embedding 接口
```

推荐使用 Qdrant 作为向量数据库，原因：

1. 部署简单。
2. 支持 payload 元数据。
3. 支持按 source_file 过滤检索。
4. 适合当前车型用户手册 RAG 项目。
5. 后续可以扩展混合检索、重排序、多 collection 管理。

---

## 5. 总体架构

整体架构如下：

```text
前端聊天页面
    ↓
FastAPI /api/v1/chat
    ↓
权限校验 current_user
    ↓
校验 conversation_id 是否属于当前用户
    ↓
保存用户问题到 messages
    ↓
Embedding Service 生成 query embedding
    ↓
Qdrant 检索相关 chunk
    ↓
根据检索结果构建 context
    ↓
Prompt Builder 构建 RAG Prompt
    ↓
LLM Service 调用大模型
    ↓
保存 assistant 回答到 messages
    ↓
保存 RAG 日志到 rag_query_logs
    ↓
返回 answer + sources
```

数据入库流程如下：

```text
chunks.jsonl
    ↓
import_chunks 脚本
    ↓
manual_documents 表
manual_chunks 表
    ↓
build_embeddings 脚本
    ↓
Embedding Service
    ↓
Qdrant 向量库
    ↓
更新 manual_chunks.embedding_status
```

---

## 6. 后端目录结构要求

在现有项目中新增或调整以下目录：

```text
app/
├── rag/
│   ├── __init__.py
│   ├── importer.py
│   ├── vector_store.py
│   ├── retriever.py
│   ├── prompt_builder.py
│   ├── rag_service.py
│   └── utils.py
│
├── models/
│   ├── manual_document.py
│   ├── manual_chunk.py
│   └── rag_query_log.py
│
├── schemas/
│   └── rag.py
│
├── api/
│   └── v1/
│       ├── chat.py
│       └── rag.py
│
├── services/
│   ├── embedding_service.py
│   └── llm_service.py
│
└── scripts/
    ├── import_chunks.py
    └── build_embeddings.py
```

说明：

1. `rag/importer.py`：负责读取 JSONL 并写入 MySQL。
2. `rag/vector_store.py`：负责 Qdrant collection 创建、写入和检索。
3. `rag/retriever.py`：负责 query embedding 和 chunk 检索。
4. `rag/prompt_builder.py`：负责构建 RAG Prompt。
5. `rag/rag_service.py`：负责完整 RAG 流程编排。
6. `services/embedding_service.py`：负责调用 embedding 模型。
7. `services/llm_service.py`：继续保留，用于 RAG 最后的答案生成。
8. `api/v1/chat.py`：现有聊天接口保留，但内部必须改为 RAG。
9. `api/v1/rag.py`：提供文档列表、检索调试等 RAG 相关接口。
10. `scripts/import_chunks.py`：命令行导入 JSONL。
11. `scripts/build_embeddings.py`：命令行构建向量索引。

---

## 7. 环境变量要求

在 `.env.example` 中补充：

```env
# Qdrant
QDRANT_URL=http://127.0.0.1:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=car_manual_chunks

# Embedding
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
EMBEDDING_DIM=1024

# RAG
RAG_TOP_K=5
RAG_SCORE_THRESHOLD=0.2
RAG_CONTEXT_MAX_CHARS=6000
RAG_RETRIEVAL_CACHE_TTL=600
RAG_QUERY_EMBEDDING_CACHE_TTL=3600
```

说明：

1. `QDRANT_COLLECTION` 默认使用 `car_manual_chunks`。
2. `EMBEDDING_DIM` 必须与实际 embedding 模型输出维度一致。
3. `RAG_TOP_K` 默认检索 5 个 chunk。
4. `RAG_SCORE_THRESHOLD` 用于过滤低相关结果。
5. `RAG_CONTEXT_MAX_CHARS` 用于限制传给大模型的上下文长度。

---

## 8. MySQL 数据表设计

### 8.1 manual_documents 表

用于记录每一本车型用户手册。

字段：

```text
id                    bigint primary key
source_file            varchar(255) unique not null
display_name           varchar(255) null
car_model_name         varchar(255) null
chunk_count            int default 0
embedding_status       varchar(50) default 'pending'
created_at             datetime
updated_at             datetime
```

字段说明：

1. `source_file`：对应 chunk 中的 `source_file`，例如 `xia.pdf`。
2. `display_name`：前端展示名称，默认可以等于 source_file。
3. `car_model_name`：车型名称，当前可以为空，后续人工补充。
4. `chunk_count`：该手册下 chunk 数量。
5. `embedding_status`：取值为 pending、processing、completed、failed。

---

### 8.2 manual_chunks 表

用于保存清洗后的 chunk 内容和元数据。

字段：

```text
id                    bigint primary key
chunk_id              varchar(255) unique not null
document_id           bigint not null
source_file           varchar(255) not null
page_idx_start        int null
page_idx_end          int null
page_number_start     varchar(50) null
page_number_end       varchar(50) null
chunk_type            varchar(50) not null
section_title         varchar(255) null
content               longtext not null
content_hash          varchar(64) not null
metadata_json         json null
vector_id             varchar(255) null
embedding_status      varchar(50) default 'pending'
created_at            datetime
updated_at            datetime
```

字段说明：

1. `chunk_id`：来自 JSONL，每个 chunk 唯一。
2. `document_id`：关联 `manual_documents.id`。
3. `source_file`：冗余保存，方便查询和过滤。
4. `content`：RAG 检索和问答正文。
5. `content_hash`：用于判断 chunk 内容是否变化，避免重复导入。
6. `metadata_json`：保存完整 metadata。
7. `vector_id`：Qdrant 中的 point id，建议与 chunk_id 一致。
8. `embedding_status`：pending、processing、completed、failed。

---

### 8.3 rag_query_logs 表

用于保存每次 RAG 问答日志。

字段：

```text
id                    bigint primary key
user_id               bigint not null
conversation_id       bigint null
user_message_id       bigint null
assistant_message_id  bigint null
query                 text not null
answer                longtext null
source_file_filter    varchar(255) null
retrieved_chunks_json json null
top_k                 int default 5
latency_ms            int null
success               boolean default true
error_message         text null
created_at            datetime
```

字段说明：

1. `user_id`：当前提问用户。
2. `conversation_id`：当前会话 ID。
3. `user_message_id`：用户问题对应的 message id。
4. `assistant_message_id`：assistant 回答对应的 message id。
5. `query`：用户问题。
6. `answer`：模型最终回答。
7. `source_file_filter`：是否限定某一本手册。
8. `retrieved_chunks_json`：保存检索命中的 chunk 信息。
9. `top_k`：检索数量。
10. `latency_ms`：完整 RAG 耗时。
11. `success`：是否成功。
12. `error_message`：错误信息。

---

## 9. Qdrant 向量库设计

Collection 名称：

```text
car_manual_chunks
```

每个 point 使用以下结构：

```json
{
  "id": "xia_p12_c003",
  "vector": [0.01, 0.02, 0.03],
  "payload": {
    "chunk_id": "xia_p12_c003",
    "source_file": "xia.pdf",
    "page_idx_start": 12,
    "page_idx_end": 13,
    "page_number_start": "10",
    "page_number_end": "11",
    "chunk_type": "text",
    "section_title": "车辆启动",
    "content": "车辆启动。启动车辆前请确认钥匙在车内……"
  }
}
```

要求：

1. point id 使用 `chunk_id`。
2. payload 必须保存 `chunk_id`。
3. payload 必须保存 `source_file`。
4. payload 必须保存 `section_title`。
5. payload 必须保存页码信息。
6. payload 必须保存 `content`。
7. 检索结果必须返回 score。
8. 检索必须支持按 `source_file` 过滤。
9. 如果 collection 不存在，导入或构建索引时自动创建。
10. collection 的向量维度必须等于 `EMBEDDING_DIM`。

---

## 10. Redis 缓存设计

### 10.1 Query Embedding 缓存

key 格式：

```text
rag:query_embedding:{query_hash}
```

用途：

```text
缓存用户问题的 embedding，避免相同问题重复调用 embedding 服务。
```

TTL：

```text
3600 秒
```

---

### 10.2 检索结果缓存

key 格式：

```text
rag:retrieval:{query_hash}:{source_file}:{top_k}
```

用途：

```text
缓存相同问题、相同手册、相同 top_k 的检索结果。
```

TTL：

```text
600 秒
```

要求：

1. 缓存的是检索结果，不是最终大模型回答。
2. 如果重新导入 chunk 或重建向量库，需要清理 RAG 缓存。
3. 不要长期缓存最终回答，避免上下文、会话状态变化后回答不一致。

---

## 11. JSONL 导入需求

### 11.1 导入方式

当前阶段使用命令行脚本导入，不做前端上传。

命令：

```bash
uv run python -m app.scripts.import_chunks --file data/chunks/xia_chunks.jsonl
```

也要支持导入整个目录：

```bash
uv run python -m app.scripts.import_chunks --dir data/chunks
```

---

### 11.2 导入逻辑

导入流程：

```text
1. 读取 JSONL 文件。
2. 逐行解析 JSON。
3. 校验必须字段。
4. 根据 source_file 创建或更新 manual_documents。
5. 计算 content_hash。
6. 判断 chunk_id 是否已存在。
7. 如果不存在，插入 manual_chunks。
8. 如果存在且 content_hash 相同，跳过。
9. 如果存在但 content_hash 不同，更新 content 和 metadata，并将 embedding_status 重置为 pending。
10. 统计导入数量、更新数量、跳过数量、失败数量。
```

必须校验字段：

```text
chunk_id
source_file
content
chunk_type
```

如果 `content` 为空，跳过该 chunk 并记录日志。

---

### 11.3 导入完成输出

脚本执行完成后输出：

```text
导入文件：xia_chunks.jsonl
source_file：xia.pdf
新增 chunks：1000
更新 chunks：20
跳过 chunks：50
失败 chunks：3
总耗时：xx 秒
```

---

## 12. Embedding 构建需求

### 12.1 构建命令

按单本手册构建：

```bash
uv run python -m app.scripts.build_embeddings --source-file xia.pdf
```

构建所有未完成的 chunk：

```bash
uv run python -m app.scripts.build_embeddings --all
```

指定批大小：

```bash
uv run python -m app.scripts.build_embeddings --source-file xia.pdf --batch-size 32
```

---

### 12.2 构建流程

流程：

```text
1. 读取 manual_chunks 中 embedding_status = pending 或 failed 的 chunk。
2. 按 batch_size 分批处理。
3. 调用 embedding_service 生成向量。
4. 将向量写入 Qdrant。
5. vector_id 使用 chunk_id。
6. 更新 manual_chunks.vector_id。
7. 更新 manual_chunks.embedding_status = completed。
8. 如果失败，记录错误，并将状态设为 failed。
9. 所有 chunk 完成后，更新 manual_documents.embedding_status = completed。
```

---

### 12.3 Embedding Service 要求

新增：

```text
app/services/embedding_service.py
```

必须提供：

```python
async def embed_text(text: str) -> list[float]:
    ...

async def embed_texts(texts: list[str]) -> list[list[float]]:
    ...
```

要求：

1. 支持 OpenAI-compatible embedding 接口。
2. 不要在业务代码中直接调用 embedding API。
3. embedding 模型、base_url、api_key 从环境变量读取。
4. 处理 API 调用失败、超时、空向量等异常。
5. 支持批量 embedding。

---

## 13. 检索需求

### 13.1 检索输入

检索输入包括：

```text
query：用户问题
source_file：可选，限制某一本手册
top_k：默认 5
```

---

### 13.2 检索流程

流程：

```text
1. 对 query 做简单清洗。
2. 对 query 生成 embedding。
3. 检查 Redis 中是否有相同 query 的 embedding 缓存。
4. 如果有，直接使用缓存。
5. 如果没有，调用 embedding_service。
6. 在 Qdrant 中检索 top_k 个相关 chunk。
7. 如果 source_file 不为空，按 source_file 过滤。
8. 根据 score_threshold 过滤低分结果。
9. 返回 chunk_id、score、source_file、section_title、页码、content。
```

---

### 13.3 检索结果格式

内部检索结果结构：

```json
{
  "chunk_id": "xia_p12_c003",
  "source_file": "xia.pdf",
  "section_title": "车辆启动",
  "page_number_start": "10",
  "page_number_end": "11",
  "chunk_type": "text",
  "score": 0.82,
  "content": "车辆启动。启动车辆前请确认钥匙在车内……"
}
```

---

## 14. Prompt 构建需求

新增：

```text
app/rag/prompt_builder.py
```

RAG Prompt 模板如下：

```text
你是一个汽车用户手册智能问答助手。

你只能根据【用户手册资料】回答问题。
如果资料中没有明确答案，请回答“根据当前用户手册资料，无法确定”。
不要编造不存在的功能、按钮、参数、配置、故障原因或操作步骤。
如果涉及驾驶安全、维修、充电、故障处理，请提醒用户注意安全，并建议以车辆实际提示和官方售后为准。
回答应简洁、清楚，优先给出操作步骤。

【用户手册资料】
{context}

【用户问题】
{query}

请根据用户手册资料回答：
```

context 格式：

```text
[资料1]
来源文件：xia.pdf
章节：车辆启动
页码：10-11
内容：车辆启动。启动车辆前请确认钥匙在车内……

[资料2]
来源文件：xia.pdf
章节：智能钥匙
页码：12
内容：……
```

要求：

1. context 不能无限拼接。
2. 总长度受 `RAG_CONTEXT_MAX_CHARS` 控制。
3. 每个资料块必须包含来源文件、章节、页码、内容。
4. 如果检索结果为空，不调用大模型，直接返回无法确定。
5. 不允许无资料时让模型自由回答。

---

## 15. 聊天接口改造需求

当前项目已有普通聊天接口。

新增 RAG 后，不再保留普通聊天能力。

保留原有接口路径：

```http
POST /api/v1/chat
```

但内部逻辑必须改造为 RAG。

---

### 15.1 请求体

```json
{
  "conversation_id": 1,
  "message": "车辆启动前需要注意什么？",
  "source_file": "xia.pdf",
  "top_k": 5
}
```

字段说明：

1. `conversation_id`：必填，当前会话 ID。
2. `message`：必填，用户问题。
3. `source_file`：可选，如果传入，则只检索指定手册。
4. `top_k`：可选，默认 5。

---

### 15.2 返回体

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "answer": "启动车辆前，需要确认钥匙在车内，并检查挡位、制动踏板和车辆状态提示……",
    "sources": [
      {
        "chunk_id": "xia_p12_c003",
        "source_file": "xia.pdf",
        "section_title": "车辆启动",
        "page_number_start": "10",
        "page_number_end": "11",
        "score": 0.82,
        "content_preview": "车辆启动。启动车辆前请确认钥匙在车内……"
      }
    ],
    "conversation_id": 1,
    "user_message_id": 10,
    "assistant_message_id": 11,
    "latency_ms": 1532
  }
}
```

---

### 15.3 `/api/v1/chat` 完整流程

流程：

```text
1. 校验用户登录状态。
2. 获取 current_user。
3. 接收 conversation_id、message、source_file、top_k。
4. 校验 conversation_id 是否属于 current_user。
5. 保存用户问题到 messages 表，role = user。
6. 调用 rag_service 执行 RAG。
7. 对 message 生成 query embedding。
8. 检索 Qdrant。
9. 如果 source_file 不为空，只检索指定手册。
10. 如果无检索结果，生成固定回答“根据当前用户手册资料，无法确定”。
11. 如果有检索结果，构建 context。
12. 构建 RAG prompt。
13. 调用 llm_service 生成答案。
14. 保存 assistant 回答到 messages 表，role = assistant。
15. 保存 rag_query_logs。
16. 返回 answer 和 sources。
```

---

## 16. 检索调试接口

新增检索调试接口：

```http
POST /api/v1/rag/search
```

该接口只检索，不调用大模型。

请求体：

```json
{
  "query": "胎压报警怎么办？",
  "source_file": "xia.pdf",
  "top_k": 5
}
```

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "胎压报警怎么办？",
    "results": [
      {
        "chunk_id": "xxx",
        "source_file": "xia.pdf",
        "section_title": "胎压监测系统",
        "page_number_start": "88",
        "page_number_end": "89",
        "score": 0.79,
        "content": "……"
      }
    ]
  }
}
```

用途：

1. 调试检索效果。
2. 判断 chunk 是否正确入库。
3. 判断 embedding 和 Qdrant 是否正常。
4. 在接入大模型前先验证召回是否正确。

---

## 17. 文档和 Chunk 查询接口

### 17.1 查询手册列表

```http
GET /api/v1/rag/documents
```

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": [
    {
      "id": 1,
      "source_file": "xia.pdf",
      "display_name": "xia.pdf",
      "car_model_name": null,
      "chunk_count": 1200,
      "embedding_status": "completed"
    }
  ]
}
```

用途：

1. 前端展示车型手册选择框。
2. 用户选择需要问答的手册。
3. 后端调试已导入文档状态。

---

### 17.2 查询某本手册 chunk

```http
GET /api/v1/rag/documents/{document_id}/chunks?page=1&page_size=20
```

返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "chunk_id": "xia_p12_c003",
        "source_file": "xia.pdf",
        "section_title": "车辆启动",
        "page_number_start": "10",
        "page_number_end": "11",
        "chunk_type": "text",
        "content_preview": "车辆启动。启动车辆前请确认钥匙在车内……",
        "embedding_status": "completed"
      }
    ],
    "total": 1200,
    "page": 1,
    "page_size": 20
  }
}
```

用途：

1. 后端调试。
2. 检查 chunk 是否正常导入。
3. 检查 embedding 状态。

---

## 18. 前端调整需求

前端现有聊天页继续保留，但不再作为普通聊天页面，而是作为用户手册问答页面。

前端需要新增：

1. 手册选择框。
2. 当前会话消息展示。
3. 用户输入框。
4. assistant 回答展示。
5. 引用来源展示区域。

用户发送消息时，请求：

```http
POST /api/v1/chat
```

请求体：

```json
{
  "conversation_id": 1,
  "message": "胎压报警怎么办？",
  "source_file": "xia.pdf",
  "top_k": 5
}
```

前端需要展示：

1. assistant 回答。
2. 引用来源。
3. 来源文件。
4. 章节标题。
5. 页码。
6. content_preview。
7. score 可选展示，调试阶段可以显示，正式页面可以隐藏。

前端不需要提供：

1. 普通聊天 / RAG 聊天切换按钮。
2. 是否启用 RAG 的开关。
3. 检索不到时普通聊天 fallback。

---

## 19. 权限要求

所有 RAG 问答接口必须要求用户登录。

具体要求：

1. `/api/v1/chat` 必须校验登录状态。
2. 如果传入 `conversation_id`，必须检查该会话属于当前用户。
3. 用户不能访问其他用户的会话。
4. 用户不能向其他用户的会话写入消息。
5. 当前阶段所有用户共享同一批公共车型用户手册。
6. 当前阶段不需要做文档级用户权限隔离。
7. 后续如支持用户私有知识库，再增加 document 权限表。

校验逻辑示例：

```text
Conversation.id == conversation_id
Conversation.user_id == current_user.id
```

---

## 20. 异常处理要求

需要处理以下异常：

1. JSONL 文件不存在。
2. JSONL 单行格式错误。
3. chunk_id 缺失。
4. source_file 缺失。
5. content 为空。
6. MySQL 写入失败。
7. Embedding 服务调用失败。
8. Embedding 维度与 Qdrant collection 维度不一致。
9. Qdrant 连接失败。
10. Qdrant collection 不存在。
11. 检索结果为空。
12. LLM 调用失败。
13. conversation_id 不存在。
14. conversation_id 不属于当前用户。
15. 用户未登录。
16. Redis 连接失败。

检索结果为空时，返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "answer": "根据当前用户手册资料，未检索到相关内容，无法确定答案。",
    "sources": [],
    "conversation_id": 1,
    "user_message_id": 10,
    "assistant_message_id": 11,
    "latency_ms": 300
  }
}
```

要求：

1. 检索为空时不调用大模型。
2. 不允许大模型自由发挥。
3. assistant 的固定回答也需要保存到 messages 表。
4. rag_query_logs 也需要记录本次检索为空。

---

## 21. 日志要求

需要记录以下日志：

1. JSONL 文件导入开始和结束。
2. chunk 新增数量。
3. chunk 更新数量。
4. chunk 跳过数量。
5. chunk 失败数量。
6. embedding 开始和结束。
7. embedding 批次耗时。
8. Qdrant 写入数量。
9. 用户 query。
10. source_file 过滤条件。
11. 检索 top_k。
12. 检索命中的 chunk_id。
13. 检索 score。
14. LLM 调用耗时。
15. RAG 总耗时。
16. RAG 异常信息。
17. conversation_id 权限校验失败信息。

---

## 22. 开发顺序

请严格按以下顺序开发，不要一次性大改项目。

### 第一步：新增数据库模型和表

新增：

```text
manual_documents
manual_chunks
rag_query_logs
```

完成后确认 MySQL 中表已创建。

---

### 第二步：实现 JSONL 导入脚本

实现：

```bash
uv run python -m app.scripts.import_chunks --file data/chunks/xia_chunks.jsonl
```

先只导入 MySQL，不做 embedding。

验收：

1. manual_documents 有数据。
2. manual_chunks 有数据。
3. chunk_id 唯一。
4. content 正常保存。
5. metadata_json 正常保存。

---

### 第三步：实现 Embedding Service

实现：

```python
async def embed_text(text: str) -> list[float]:
    ...

async def embed_texts(texts: list[str]) -> list[list[float]]:
    ...
```

验收：

1. 单条文本可以返回向量。
2. 多条文本可以批量返回向量。
3. 向量维度等于 EMBEDDING_DIM。
4. 出错时有明确异常日志。

---

### 第四步：实现 Qdrant Vector Store

实现：

1. 创建 collection。
2. 检查 collection 是否存在。
3. upsert chunk 向量。
4. search。
5. source_file filter。

验收：

1. collection 可以创建。
2. chunk 向量可以写入。
3. query 可以搜到结果。
4. source_file 过滤有效。

---

### 第五步：实现 build_embeddings 脚本

实现：

```bash
uv run python -m app.scripts.build_embeddings --source-file xia.pdf
```

验收：

1. pending chunk 可以被批量向量化。
2. Qdrant 中有对应 point。
3. manual_chunks.embedding_status 更新为 completed。
4. manual_documents.embedding_status 更新为 completed。

---

### 第六步：实现 `/api/v1/rag/search`

先做检索调试接口，不调用大模型。

验收：

1. 输入问题可以返回相关 chunk。
2. 返回结果包含 chunk_id、source_file、section_title、页码、score、content。
3. source_file 过滤有效。

---

### 第七步：实现 RAG Service

实现：

```text
query → embedding → retrieval → context → prompt → llm → answer + sources
```

验收：

1. 有检索结果时可以生成基于手册的答案。
2. 无检索结果时返回固定无法确定答案。
3. sources 正常返回。

---

### 第八步：改造 `/api/v1/chat`

把原普通聊天接口改成 RAG 聊天接口。

验收：

1. 所有聊天问题都走 RAG。
2. 不再直接调用普通聊天。
3. 用户消息保存正常。
4. assistant 回答保存正常。
5. sources 返回正常。
6. rag_query_logs 保存正常。

---

### 第九步：前端接入

前端聊天页增加：

1. 手册选择框。
2. 引用来源展示。
3. RAG 回答展示。

验收：

1. 用户选择手册后可以提问。
2. 页面显示答案。
3. 页面显示引用来源。
4. 刷新后历史消息仍存在。

---

## 23. 验收标准

最终完成后必须满足：

1. 可以导入 JSONL chunk 文件。
2. MySQL 中存在 manual_documents 数据。
3. MySQL 中存在 manual_chunks 数据。
4. 可以成功调用 embedding 服务。
5. 可以成功把 chunk 向量写入 Qdrant。
6. 可以通过 `/api/v1/rag/search` 检索到相关 chunk。
7. 可以通过 `/api/v1/chat` 完成 RAG 问答。
8. `/api/v1/chat` 不再提供普通聊天能力。
9. 所有用户问题都必须先检索用户手册。
10. 回答必须包含 sources。
11. sources 包含 chunk_id、source_file、section_title、page_number_start、page_number_end、score、content_preview。
12. 如果检索不到内容，不允许模型胡编。
13. 用户问题保存到 messages 表。
14. assistant 回答保存到 messages 表。
15. rag_query_logs 保存每次 RAG 检索记录。
16. conversation_id 必须校验属于当前用户。
17. 前端可以选择手册。
18. 前端可以展示引用来源。
19. 原有登录、注册、会话管理功能不受影响。
20. 删除会话、查询会话、消息历史功能不受影响。

---

## 24. 当前阶段不要做的事情

当前阶段明确不要做：

1. 不要重新解析 PDF。
2. 不要重新清洗数据。
3. 不要在线上传 PDF。
4. 不要做 OCR。
5. 不要做图片 RAG。
6. 不要做多模态 RAG。
7. 不要做 Agent。
8. 不要做工具调用。
9. 不要做普通聊天和 RAG 聊天双模式。
10. 不要做“检索不到就普通聊天回答”的 fallback。
11. 不要让用户选择是否启用 RAG。
12. 不要每次提问都重新读取 JSONL。
13. 不要每次提问都重新 embedding 所有 chunk。
14. 不要把 RAG 逻辑全部写在接口函数里。
15. 不要破坏现有用户登录和会话系统。
16. 不要删除 `llm_service.py`，因为 RAG 仍然需要调用大模型。
17. 不要删除权限校验。
18. 不要忽略 conversation_id 和 user_id 的归属校验。

---

## 25. 给 Codex 的执行要求

请根据本需求文档，在现有项目基础上增量开发 RAG 模块。

要求：

1. 先阅读当前项目结构。
2. 不要重建整个项目。
3. 不要破坏现有登录、会话、消息保存功能。
4. 不要删除已有可用接口。
5. 优先实现后端 RAG 能力。
6. 先实现 JSONL 入库和检索调试，再改造聊天接口。
7. 每一步完成后给出修改文件列表。
8. 每一步完成后说明如何运行和验证。
9. 如果发现现有字段名、模型名、接口路径与需求文档不一致，以当前项目实际代码为准，并说明差异。
10. 所有新增代码应保持清晰分层，不要把所有逻辑写在一个接口函数中。
