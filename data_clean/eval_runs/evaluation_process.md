# RAG 评估流程说明

本文档说明 `backend/app/scripts/evaluate_rag.py` 的运行方式、依赖、输出文件，以及各指标的具体计算方式。

## 1. 运行方式

在 `backend` 目录运行：

```powershell
cd D:\Users\22726\Desktop\Agent\backend
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5
```

只跑前 N 条：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5 --limit 5
```

加入答案生成评估：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5 --generate-answers
```

加入 LLM judge 评估：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5 --llm-judge
```

调整 Context Precision 的相关性阈值：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5 --context-relevance-threshold 0.35
```

## 2. 运行依赖

检索评估需要：

- Qdrant 已启动
- Qdrant 中已有 chunk 向量
- Embedding 服务可用
- `.env` 中 embedding 配置正确

检索评估不需要：

- 不需要启动 FastAPI 服务
- 不需要 MySQL
- 不需要 Redis

如果使用 `--generate-answers` 或 `--llm-judge`，还需要：

- LLM 服务可用
- `.env` 中 LLM 配置正确

## 3. 输入数据

默认读取：

```text
D:\Users\22726\Desktop\Agent\data_clean\eval.jsonl
```

每条测试数据主要使用这些字段：

```json
{
  "case_id": "manual_002",
  "source_file": "xia.pdf",
  "question": "车辆在充电过程中出现异味或冒烟时应该怎么处理？",
  "gold_answer": "标准答案",
  "gold_evidence": "标准证据说明",
  "gold_pages": ["144"],
  "gold_chunk_ids": ["xia_p2_c005"]
}
```

## 4. 输出文件

默认输出到：

```text
D:\Users\22726\Desktop\Agent\data_clean\eval_runs\
```

检索评估输出：

```text
retrieval_top5_results.jsonl
retrieval_top5_summary.json
```

端到端答案评估输出：

```text
end_to_end_top5_results.jsonl
end_to_end_top5_summary.json
```

LLM judge 评估输出：

```text
llm_judge_top5_results.jsonl
llm_judge_top5_summary.json
```

`results.jsonl` 是逐 case 结果，`summary.json` 是整体平均指标。

## 5. 单条 Case 的评估流程

对每条测试数据：

1. 读取 `question`
2. 调用现有 `retrieve_chunks()`
3. 按配置执行纯向量检索或 hybrid 检索
4. 提取：
   - `retrieved_chunk_ids`
   - `retrieved_pages`
   - `retrieved chunk content`
5. 和标注字段对比：
   - `gold_chunk_ids`
   - `gold_pages`
   - `gold_evidence`，没有时退回 `gold_answer`
6. 计算检索指标
7. 如果启用 `--generate-answers`，再调用 LLM 生成答案，并计算答案相似度指标
8. 如果启用 `--llm-judge`，会先生成答案，再调用 LLM judge 对答案和上下文打分

当前 `retrieve_chunks()` 支持两种策略：

```text
RAG_RETRIEVAL_STRATEGY=vector
RAG_RETRIEVAL_STRATEGY=hybrid
```

默认是：

```text
RAG_RETRIEVAL_STRATEGY=hybrid
```

## 5.1 Hybrid 检索流程

Hybrid 检索按下面顺序执行：

```text
1. 向量召回
2. BM25 稀疏召回
3. RRF 融合排序
4. 查询相关性重排，选出 top-k seed chunks
5. 对每个 seed chunk 注入邻近 chunk 内容
6. 返回 top-k 个扩展后的证据块
```

### 向量召回

使用原来的 Qdrant 向量检索：

```text
QdrantVectorStore.search(...)
```

召回数量由配置控制：

```text
RAG_VECTOR_RECALL_K=20
```

### BM25 稀疏召回

BM25 稀疏索引来自：

```text
D:\Users\22726\Desktop\Agent\data_clean\chunks.jsonl
```

配置项：

```text
RAG_CHUNKS_JSONL_PATH=../data_clean/chunks.jsonl
RAG_SPARSE_RECALL_K=20
```

当前稀疏检索不依赖额外库，脚本会在内存中构建倒排索引。

中文分词采用轻量规则：

```text
中文单字 + 中文 bigram + 英文/数字 token
```

例如：

```text
车辆充电异味
```

会产生类似：

```text
车, 辆, 充, 电, 异, 味, 车辆, 辆充, 充电, 电异, 异味
```

### RRF 融合排序

向量召回和稀疏召回会用 RRF 融合。

单个召回源中，第 `rank` 位的分数：

```text
rrf_score = weight / (RAG_RRF_K + rank)
```

默认：

```text
RAG_RRF_K=60
RAG_VECTOR_RRF_WEIGHT=1.0
RAG_SPARSE_RRF_WEIGHT=1.0
```

如果同一个 chunk 同时被向量和稀疏召回命中，会把两个 RRF 分数相加。

### 重排选 seed

融合后会做一次轻量重排，并直接选出最终的 top-k seed chunks。

最终分数：

```text
final_score = 0.7 * normalized_fused_score + 0.3 * lexical_relevance
```

其中：

```text
lexical_relevance = query tokens 和 chunk tokens 的交集比例
```

例如命令行传入：

```text
--top-k 5
```

则重排后选出 5 个 seed chunks。`retrieved_chunk_ids` 记录的就是这 5 个 seed chunk id。

### 邻近 chunk 内容注入

对选出的 top-k seed chunks 做前后邻居扩展。

配置：

```text
RAG_CHUNK_EXPANSION_WINDOW=1
```

含义：

```text
每个 seed chunk 向前扩展 1 个 chunk，向后扩展 1 个 chunk
```

例如命中：

```text
xia_p2_c005
```

可能扩展出：

```text
xia_p2_c004
xia_p3_c006
```

最终返回给大模型的仍然是 5 个证据块，但每个证据块的 `content` 会变成：

```text
[neighbor chunk_id=xia_p2_c004 page=...]
...

[seed chunk_id=xia_p2_c005 page=...]
...

[neighbor chunk_id=xia_p3_c006 page=...]
...
```

这个证据块自己的 `chunk_id` 仍然保留 seed id：

```text
xia_p2_c005
```

同时结果里会记录：

```json
"retrieved_context_chunk_ids": [
  ["xia_p2_c004", "xia_p2_c005", "xia_p3_c006"]
]
```

这样：

- `retrieved_chunk_ids` 仍然稳定表示 seed chunks，适合和 `gold_chunk_ids` 对比
- 大模型看到的是扩展后的局部上下文
- 扩展 chunk 不参与第二次排名竞争，因此不需要第二次重排

## 6. Chunk 指标

### chunk_hit

含义：这一题是否至少命中一个标准 chunk。

计算：

```text
gold_chunk_set = set(gold_chunk_ids)
retrieved_chunk_set = set(retrieved_chunk_ids)
chunk_hit = len(gold_chunk_set ∩ retrieved_chunk_set) > 0
```

例子：

```text
gold_chunk_ids = ["xia_p2_c005"]
retrieved_chunk_ids = ["xia_p2_c005", "xia_p3_c006"]
chunk_hit = true
```

### chunk_hit_rate

含义：所有成功 case 中，`chunk_hit = true` 的比例。

计算：

```text
chunk_hit_rate = 命中正确 chunk 的 case 数 / 成功评估的 case 数
```

### chunk_recall

含义：标准 chunk 被召回了多少。

单条 case：

```text
chunk_recall = len(gold_chunk_set ∩ retrieved_chunk_set) / len(gold_chunk_set)
```

整体 summary：

```text
chunk_recall = 所有成功 case 的 chunk_recall 平均值
```

例子：

```text
gold_chunk_ids = ["c1", "c2", "c3"]
retrieved_chunk_ids = ["c1", "c2", "x"]
chunk_recall = 2 / 3
```

### chunk_precision

含义：检索出来的 chunk 中，有多少是标准 chunk。

单条 case：

```text
chunk_precision = len(gold_chunk_set ∩ retrieved_chunk_set) / len(retrieved_chunk_set)
```

整体 summary：

```text
chunk_precision = 所有成功 case 的 chunk_precision 平均值
```

例子：

```text
gold_chunk_ids = ["c1"]
retrieved_chunk_ids = ["c1", "x1", "x2", "x3", "x4"]
chunk_precision = 1 / 5 = 0.2
```

## 7. 排名指标

### mrr

含义：正确 chunk 排得越靠前，分数越高。

单条 case：

```text
如果第 rank 个检索结果命中 gold_chunk_ids：
mrr = 1 / rank

如果没有任何命中：
mrr = 0
```

例子：

```text
正确 chunk 排第 1：mrr = 1
正确 chunk 排第 2：mrr = 0.5
正确 chunk 排第 3：mrr = 0.3333
```

整体 summary：

```text
mrr = 所有成功 case 的 mrr 平均值
```

## 8. Page 指标

### page_hit

含义：这一题是否至少命中一个标准页码。

计算：

```text
gold_page_set = set(gold_pages)
retrieved_page_set = set(retrieved_pages)
page_hit = len(gold_page_set ∩ retrieved_page_set) > 0
```

### page_hit_rate

含义：所有成功 case 中，`page_hit = true` 的比例。

计算：

```text
page_hit_rate = 命中正确页码的 case 数 / 成功评估的 case 数
```

### page_recall

含义：标准页码被召回了多少。

单条 case：

```text
page_recall = len(gold_page_set ∩ retrieved_page_set) / len(gold_page_set)
```

整体 summary：

```text
page_recall = 所有成功 case 的 page_recall 平均值
```

例子：

```text
gold_pages = ["150", "151"]
retrieved_pages = ["150", "160"]
page_recall = 1 / 2 = 0.5
```

## 9. Context 指标

Context 指标不是简单看 `chunk_id` 或页码，而是看检索内容本身是否覆盖标准证据。

当前实现是轻量内容级评估，不调用 LLM judge。

标准参考文本：

```text
gold_reference = gold_evidence if gold_evidence else gold_answer
```

文本归一化：

1. 转小写
2. 去标点
3. 去空白字符
4. 按字符计算重叠

### context_recall

含义：标准证据中的信息，有多少被检索上下文覆盖。

计算：

```text
retrieved_context = top-k chunks 的 content 拼接
context_recall = char_recall(retrieved_context, gold_reference)
```

其中：

```text
char_recall(prediction, reference)
= prediction 和 reference 的字符重叠数 / reference 的字符数
```

直观理解：

```text
如果 gold_evidence 里的关键信息基本都出现在检索上下文里，context_recall 高。
如果检索内容漏掉了标准证据，context_recall 低。
```

### context_relevance_scores

含义：每个检索 chunk 对标准证据的覆盖度。

对每个 chunk：

```text
score_i = char_recall(chunk_i.content, gold_reference)
```

输出示例：

```json
"context_relevance_scores": [0.91, 0.12, 0.05, 0.0, 0.0]
```

表示第一个 chunk 和标准证据最相关。

### context_precision

含义：相关上下文是否排得靠前。

先用阈值判断某个 chunk 是否相关：

```text
score_i >= context_relevance_threshold
```

默认：

```text
context_relevance_threshold = 0.35
```

然后按排名计算平均精度：

```text
relevant_seen = 0
precision_sum = 0

遍历第 rank 个 chunk：
  如果该 chunk 相关：
    relevant_seen += 1
    precision_sum += relevant_seen / rank

context_precision = precision_sum / relevant_seen
```

如果没有任何 chunk 达到相关阈值：

```text
context_precision = 0
```

例子：

```text
context_relevance_scores = [0.80, 0.10, 0.60, 0.05, 0.40]
threshold = 0.35

相关 chunk 排名：1, 3, 5

rank=1: precision = 1 / 1 = 1.0
rank=3: precision = 2 / 3 = 0.6667
rank=5: precision = 3 / 5 = 0.6

context_precision = (1.0 + 0.6667 + 0.6) / 3 = 0.7556
```

## 10. 答案生成指标

只有运行 `--generate-answers` 时才计算。

### answer_exact_match

含义：生成答案归一化后是否和标准答案完全一致。

计算：

```text
answer_exact_match = normalize_text(answer) == normalize_text(gold_answer)
```

这个指标通常很严格，RAG 问答里不一定高。

### answer_char_f1

含义：生成答案和标准答案的字符级 F1。

计算：

```text
precision = 重叠字符数 / 生成答案字符数
recall = 重叠字符数 / 标准答案字符数
answer_char_f1 = 2 * precision * recall / (precision + recall)
```

如果没有重叠：

```text
answer_char_f1 = 0
```

### answer_rouge_l

含义：基于最长公共子序列的答案相似度。

计算：

```text
lcs = 生成答案和标准答案的最长公共子序列长度
precision = lcs / 生成答案字符数
recall = lcs / 标准答案字符数
answer_rouge_l = 2 * precision * recall / (precision + recall)
```

## 11. latency_ms

## 11. LLM Judge 指标

只有运行 `--llm-judge` 时才计算。

`--llm-judge` 会自动生成答案，因此不需要同时加 `--generate-answers`。

Judge 输入：

```text
question
gold_answer
gold_evidence
retrieved_context
answer
```

Judge 要求模型只输出 JSON：

```json
{
  "answer_correctness": 0,
  "faithfulness": 0,
  "evidence_coverage": 0,
  "context_relevance": 0,
  "hallucination": false,
  "reason": "一句话说明主要依据"
}
```

### judge_answer_correctness

含义：模型答案和标准答案的语义一致程度。

范围：

```text
0 到 5
```

解释：

```text
5 = 语义完全正确
3 = 部分正确，但有遗漏或轻微错误
0 = 基本错误或没有回答问题
```

summary 中：

```text
answer_correctness = 所有 judge 成功 case 的 judge_answer_correctness 平均值
```

### judge_faithfulness

含义：模型答案是否被检索上下文支持，也就是忠实度。

范围：

```text
0 到 5
```

解释：

```text
5 = 答案中的关键事实都能从 retrieved_context 找到依据
3 = 大体有依据，但部分表述缺少支持
0 = 主要内容没有上下文依据
```

summary 中：

```text
faithfulness = 所有 judge 成功 case 的 judge_faithfulness 平均值
```

### judge_evidence_coverage

含义：检索上下文是否覆盖标准证据中回答问题所需的信息。

范围：

```text
0 到 5
```

解释：

```text
5 = 检索上下文充分覆盖 gold_evidence
3 = 覆盖部分证据，但有明显遗漏
0 = 几乎没有覆盖标准证据
```

summary 中：

```text
evidence_coverage = 所有 judge 成功 case 的 judge_evidence_coverage 平均值
```

### judge_context_relevance

含义：检索上下文和问题是否相关。

范围：

```text
0 到 5
```

解释：

```text
5 = 上下文高度相关，基本都围绕问题
3 = 有部分相关内容，也混入明显无关内容
0 = 上下文基本无关
```

summary 中：

```text
context_relevance = 所有 judge 成功 case 的 judge_context_relevance 平均值
```

### judge_hallucination

含义：模型答案是否包含检索上下文或标准证据无法支持的关键事实。

单条 case：

```text
true = 存在幻觉或无依据关键事实
false = 未发现明显幻觉
```

summary 中：

```text
hallucination_rate = judge_hallucination 为 true 的比例
```

### judge_reason

含义：LLM judge 给出的一句话理由，方便人工抽查。

### judge_raw_response / judge_error

`judge_raw_response` 保存 judge 原始输出。

如果 judge 输出不是合法 JSON，或缺少必要字段：

```text
judge_error = 错误信息
```

注意：`judge_error` 不会让整条 case 的检索评估失败，只表示 judge 结果不可用。

## 12. latency_ms

含义：单条 case 的耗时，单位毫秒。

计算范围：

```text
从开始评估该 case 到该 case 结束
```

如果只做检索评估，主要包含：

- embedding 查询向量生成
- Qdrant 检索
- 指标计算

如果加 `--generate-answers`，还包含：

- LLM 生成答案耗时

如果加 `--llm-judge`，还包含：

- LLM 生成答案耗时
- LLM judge 打分耗时

## 13. failed / successful

如果某条 case 抛异常，例如：

- embedding 服务不可用
- Qdrant 未启动
- LLM 调用失败

该 case 会记录：

```json
"error": "错误信息"
```

summary 中：

```text
successful = error 为空的 case 数
failed = error 非空的 case 数
```

整体指标只对 `successful` case 求平均。

## 14. 当前评估的边界

当前 Context Recall / Context Precision 是轻量算法：

- 优点：快，不需要额外 LLM 调用，适合日常回归
- 缺点：只能看字符内容覆盖，不能真正判断语义等价、事实支持、幻觉

更严格的 RAG 评估通常会再加 LLM judge，例如：

- faithfulness：答案是否完全被上下文支持
- answer correctness：答案语义是否正确
- evidence coverage：证据是否覆盖答案所需信息
- context relevance：上下文是否真的和问题相关

本脚本已经支持 `--llm-judge`，但仍有两个注意点：

- 默认使用项目当前配置的同一个 LLM 作为 judge，如果答案生成模型和 judge 模型相同，评估不够独立。
- LLM judge 是语义评估，比字符指标更接近人工判断，但仍可能受提示词、模型能力和输出稳定性影响。
## 当前查询改写后的评估口径补充

当前线上聊天链路已经不是单次 `retrieve_chunks(question)`，而是：

```text
question
-> rewrite_query(question)
-> retrieve_rewritten_query_seeds(rewrite)
   - 原问题：混合检索 top_k
   - 改写问题：混合检索 top_k
   - 最多 3 个子问题：分别混合检索 top_k
   - keywords：稀疏关键词检索 top_k
   - chunk_id 去重
   - SOURCE_WEIGHTS + rank fusion 全局排序
   - 取 RAG_FINAL_SEED_TOP_K 个 seed chunk
-> expand_chunk_contexts(seeds)
-> build_rag_prompt(question, expanded_chunks)
```

因此新版 `evaluate_rag.py` 默认也走这条新链路，保证评估结果和聊天接口一致。

如果需要旧口径对比，可以加：

```powershell
.\.venv\Scripts\python.exe -m app.scripts.evaluate_rag --top-k 5 --no-query-rewrite
```

注意：开启查询改写后，即使文件名仍是 `retrieval_top5_results.jsonl`，其中 `top5` 表示“每一路召回 top_k=5”，最终进入指标计算的是全局排序后的最多 10 个 seed chunk 以及补邻居后的上下文。

已有的 `retrieval_top5_summary.json`、`llm_judge_top5_summary.json` 是旧结果文件，不能直接代表当前查询改写后的新链路。重新运行评估后会覆盖这些文件。
