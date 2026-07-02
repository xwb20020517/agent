# RAG 检索实现说明

## 1. 关键词检索

这个项目里的关键词检索是一条**本地 BM25 稀疏检索链路**。它不是直接用 Qdrant 做全文检索，也没有部署 Elasticsearch / OpenSearch，而是后端启动后读取 `data_clean/chunks.jsonl`，在内存里构建倒排索引。

它的定位是：补足向量检索对**精确术语、数字、按钮名、故障现象、保养里程**这类信息召回不稳定的问题。

核心代码：

```text
backend/app/rag/sparse_index.py
backend/app/rag/retriever.py
backend/app/services/query_rewrite_service.py
backend/app/core/config.py
```

### 1.1 整体流程

关键词检索可以按下面这条链路理解：

```text
服务启动 / 第一次检索
-> 读取 data_clean/chunks.jsonl
-> 提取 chunk_id、source_file、section_title、page_number、content
-> 对 section_title + content 分词
-> 构建倒排索引 inverted_index

用户提问
-> query rewrite 提取 keywords
-> keywords 拼成 keyword_query
-> keyword_query 分词
-> 通过倒排索引找到候选 chunk
-> 用 BM25 给候选 chunk 打分
-> 按分数排序取 top-k
-> 返回 RetrievedChunk
-> 和 Qdrant 向量召回结果做 RRF 融合
```

一句话版：

```text
先离线/启动时把 chunks.jsonl 建成倒排索引，查询时把关键词也分词，用 BM25 找最匹配的 chunk，再和向量检索融合。
```

### 1.2 第一步：读取 chunks.jsonl

关键词检索的数据源是：

```text
data_clean/chunks.jsonl
```

配置项：

```python
RAG_CHUNKS_JSONL_PATH = BASE_DIR.parent / "data_clean" / "chunks.jsonl"
```

`SparseChunkIndex` 会逐行读取 JSONL，把每条 chunk 转成 `ChunkRecord`。

每条记录主要保留：

```text
chunk_id
source_file
section_title
page_number_start
page_number_end
chunk_type
content
```

所以关键词检索查的不是 MySQL，也不是 Qdrant，而是基于 `chunks.jsonl` 构建出来的内存索引。

### 1.3 第二步：对 chunk 建索引

每个 chunk 参与关键词检索的文本是：

```text
section_title + content
```

也就是说，章节标题和正文都会进入关键词索引。

这样做的原因是：有些 chunk 的正文可能没有反复出现功能名，但标题里有，例如：

```text
section_title = "制动摩擦块检查"
content = "首保后每12个月或20000km..."
```

如果只索引正文，用户搜“制动摩擦块”可能召回不稳定；把标题一起索引，命中会更稳。

索引结构主要包括：

```text
records          所有 chunk
record_by_id     chunk_id -> chunk
ids_by_source    每个 source_file 下的 chunk 顺序
inverted_index   token -> [(doc_index, term_freq)]
doc_freq         token 出现在多少个 chunk 中
doc_lengths      每个 chunk 的 token 数
avg_doc_length   平均 chunk 长度
```

其中最关键的是：

```text
inverted_index
```

它可以快速回答：

```text
某个关键词出现在哪些 chunk 里？
在每个 chunk 里出现了几次？
```

### 1.4 第三步：分词

代码在 `sparse_index.py` 的 `tokenize()`。

当前规则是：

```text
英文/数字：按连续字母数字提取
中文：拆成单字
中文：额外生成相邻 bigram
```

例如：

```text
制动摩擦块
```

会得到：

```text
制
动
摩
擦
块
制动
动摩
摩擦
擦块
```

再比如：

```text
20000km
```

会作为一个英文/数字 token：

```text
20000km
```

这套方案比较轻量，不依赖 jieba、HanLP、Elasticsearch / OpenSearch。它适合当前小规模 RAG 项目验证 hybrid retrieval，但不是企业级中文检索的最终形态。

企业生产环境通常会升级为：

```text
Elasticsearch / OpenSearch
+ 中文分词器
+ 汽车领域词典
+ 同义词词典
+ 字段权重
+ reranker
```

比如把这些词作为领域词保留下来：

```text
制动摩擦块
动力电池
胎压监测系统
智能钥匙
自适应巡航
```

当前项目不用 ES 的原因主要是：

```text
语料规模小，当前只有几千级 chunk
关键词检索只是向量召回的补充
不想额外增加 ES 服务部署和数据同步复杂度
先用轻量 BM25 验证 hybrid retrieval 效果
```

### 1.5 第四步：用户问题进入关键词检索

普通 hybrid 检索里，用户原问题会走两路：

```text
向量检索：embed query -> Qdrant search
关键词检索：tokenize query -> BM25 search
```

对应代码：

```python
vector_chunks = await _vector_recall(...)
sparse_chunks = _sparse_recall(...)
```

如果聊天链路启用了查询改写，还会多一条 keywords 检索：

```text
用户问题
-> rewrite_query()
-> 得到 keywords
-> keyword_query = " ".join(keywords)
-> retrieve_sparse_chunks(keyword_query)
```

例如用户问：

```text
保养的时候制动摩擦块多久检查一次？
```

查询改写可能得到：

```json
{
  "rewritten_query": "车辆保养时制动摩擦块的检查周期是什么？",
  "keywords": ["制动摩擦块", "保养项目", "保养时间", "20000km"]
}
```

于是关键词检索实际会查：

```text
制动摩擦块 保养项目 保养时间 20000km
```

这比只查用户原句更容易命中手册里的表格字段。

### 1.6 第五步：通过倒排索引找候选 chunk

假设查询是：

```text
制动摩擦块 保养项目 20000km
```

分词后会得到一组 token，例如：

```text
制、动、摩、擦、块、制动、摩擦、擦块、保养、项目、20000km
```

系统会去 `inverted_index` 里查这些 token 出现在哪些 chunk 中。

可能得到候选：

```text
chunk_A：包含 "制动摩擦块"、"保养项目"、"20000km"
chunk_B：包含 "保养项目"、"20000km"
chunk_C：只包含 "制动"
chunk_D：只包含 "保养"
```

这些 chunk 都是候选，但分数不会一样。

### 1.7 第六步：按 source_file 过滤

如果用户在前端选择了某一本手册，例如：

```text
source_file = "xia.pdf"
```

那么 BM25 计算时会跳过其他手册的 chunk：

```python
if source_file and record.source_file != source_file:
    continue
```

这样可以避免用户问“夏”的问题时，把“唐”或“汉”的手册内容召回出来。

### 1.8 第七步：BM25 打分

候选 chunk 找出来后，会用 BM25 计算相关性分数。

BM25 大致关注三件事：

```text
1. 查询词在 chunk 中出现得越多，分数越高
2. 查询词越稀有，分数越高
3. chunk 太长时，会有长度惩罚
```

代码中的参数：

```text
k1 = 1.5
b = 0.75
```

还是刚才的例子：

```text
query = "制动摩擦块 保养项目 20000km"
```

如果有两个 chunk：

```text
chunk_A:
保养项目：检查制动摩擦块和制动盘
保养时间和里程间隔：首保后每12个月或20000km

chunk_B:
保养项目：检查冷却水管有无损伤
保养时间和里程间隔：首保后每12个月或20000km
```

两个 chunk 都命中了：

```text
保养项目
20000km
```

但 `chunk_A` 额外命中了：

```text
制动摩擦块
```

所以 `chunk_A` 的 BM25 分数通常会高于 `chunk_B`。

最后按分数排序，取 top-k。

配置项：

```python
RAG_SPARSE_RECALL_K = 20
```

表示关键词检索默认召回 20 个候选 chunk。

### 1.9 第八步：返回 RetrievedChunk

BM25 检索返回的不是原始 JSON，而是统一包装成 `RetrievedChunk`。

包含：

```text
chunk_id
source_file
section_title
page_number_start
page_number_end
chunk_type
score
content
```

这样后续不管这个 chunk 来自 Qdrant 向量检索，还是来自 BM25 关键词检索，都可以用统一结构参与融合排序和构造 prompt。

### 1.10 第九步：和向量检索做 RRF 融合

默认配置：

```python
RAG_RETRIEVAL_STRATEGY = "hybrid"
```

所以最终不是只看关键词检索，而是同时使用：

```text
Qdrant 向量召回
本地 BM25 关键词召回
```

两路结果用 RRF 融合：

```text
rrf_score = weight / (RAG_RRF_K + rank)
```

默认配置：

```python
RAG_RRF_K = 60
RAG_VECTOR_RRF_WEIGHT = 1.0
RAG_SPARSE_RRF_WEIGHT = 1.0
```

融合逻辑可以理解为：

```text
如果一个 chunk 在向量检索里排得靠前，会加分
如果一个 chunk 在关键词检索里排得靠前，也会加分
如果同一个 chunk 两路都命中，分数相加，更容易排到前面
```

例子：

```text
向量召回：
1. chunk_X
2. chunk_A
3. chunk_Y

关键词召回：
1. chunk_A
2. chunk_B
3. chunk_Z
```

`chunk_A` 两路都出现，而且关键词检索排名第 1，融合后通常会靠前。

这就是 hybrid retrieval 的价值：语义相似和关键词精确命中可以互相补。

### 1.11 第十步：查询改写 keywords 的额外融合

在当前聊天链路里，查询改写会生成：

```text
original_query
rewritten_query
sub_queries
keywords
```

其中：

```text
original_query / rewritten_query / sub_queries
```

会走 hybrid 检索。

而：

```text
keywords
```

会拼成 keyword query，单独走一次 sparse-only 检索。

然后通过 `_merge_ranked_candidates()` 融合到全局候选里。

不同来源有不同权重：

```python
RAG_SOURCE_WEIGHT_ORIGINAL_QUERY = 1.3
RAG_SOURCE_WEIGHT_REWRITTEN_QUERY = 1.1
RAG_SOURCE_WEIGHT_SUB_QUERY = 1.0
RAG_SOURCE_WEIGHT_KEYWORDS = 0.8
```

这里 keywords 权重较低，是因为它只是一组关键词，不是完整问题；但它对专业词、参数、按钮名的补召回很有价值。

### 1.12 Redis 缓存

关键词检索结果会缓存到 Redis。

sparse-only 检索的缓存 key 形态是：

```text
rag:retrieval:sparse-only:seed-only:{query_hash}:{source_file}:{top_k}
```

缓存时间：

```python
RAG_RETRIEVAL_CACHE_TTL = 600
```

也就是 10 分钟。

这样同一个问题短时间内重复搜索，不需要重复计算 BM25。

### 1.13 贯穿例子

以这个问题为例：

```text
保养时制动摩擦块多久检查一次？
```

完整链路是：

```text
1. rewrite_query 理解用户问题
   rewritten_query = "车辆保养时制动摩擦块的检查周期是什么？"
   keywords = ["制动摩擦块", "保养项目", "保养时间", "20000km"]

2. keywords 拼接
   keyword_query = "制动摩擦块 保养项目 保养时间 20000km"

3. keyword_query 分词
   得到中文单字、bigram、数字 token

4. 查倒排索引
   找到包含 "制动摩擦块"、"保养项目"、"20000km" 的候选 chunk

5. BM25 打分
   同时命中 "制动摩擦块" 和 "20000km" 的 chunk 分数更高

6. source_file 过滤
   如果用户选择 xia.pdf，就只保留 xia.pdf 里的候选

7. 返回 sparse chunks
   例如 chunk_A 排名靠前

8. 和 Qdrant 向量召回做 RRF 融合
   如果 chunk_A 在向量和关键词两路都命中，最终排名会进一步上升

9. 进入上下文扩展和 prompt 构造
   最终作为引用来源和回答依据返回给前端
```

### 1.14 面试表达

可以这样讲：

> 我们项目里的关键词检索是本地实现的 BM25 稀疏召回。服务启动或第一次检索时，会读取 `chunks.jsonl`，把每个 chunk 的标题和正文做轻量分词，然后构建倒排索引。用户提问后，系统会先做查询改写，提取适合关键词检索的 keywords，比如“制动摩擦块、保养项目、20000km”。这些关键词会被拼成 keyword query，再用同样的分词规则去倒排索引里找候选 chunk，然后用 BM25 根据词频、稀有度和文本长度打分排序。关键词检索结果会和 Qdrant 的向量召回结果通过 RRF 融合，如果同一个 chunk 两路都命中，它的最终排名会更靠前。这个方案适合当前小规模语料和原型验证；如果上生产并且语料变大，我会把关键词检索升级成 Elasticsearch / OpenSearch，配中文分词、领域词典、同义词和 reranker。

## 2. 查询改写

查询改写主要在这个文件里：

```text
backend/app/services/query_rewrite_service.py
```

聊天链路调用位置：

```text
backend/app/services/chat_service.py
```

评估链路调用位置：

```text
backend/app/scripts/evaluate_rag.py
```

### 2.1 查询改写解决什么问题

用户的原始问题经常不适合直接检索，例如：

```text
它怎么关？
这个报警怎么办？
多久检查一次？
上面那个功能在哪里设置？
```

这些问题对人来说能理解，因为有聊天上下文；但对检索系统来说信息不足。

查询改写的目的就是把用户问题变成更适合检索的形式：

```text
补全历史指代
提取汽车手册里的专业术语
把口语表达改成手册表达
拆分多个子问题
提取适合关键词检索的 keywords
```

### 2.2 改写结果结构

改写结果由 `QueryRewriteResult` 表示，核心字段是：

```python
original_query: str
rewritten_query: str
keywords: list[str]
sub_queries: list[str]
used_llm: bool
```

含义：

| 字段 | 作用 |
| --- | --- |
| `original_query` | 用户原始问题，做基础清洗后保留。 |
| `rewritten_query` | 适合向量检索的完整自然语言问题。 |
| `keywords` | 适合关键词检索的手册术语。 |
| `sub_queries` | 多意图问题拆出来的子问题，最多 3 个。 |
| `used_llm` | 是否成功使用 LLM 改写；失败时会 fallback。 |

### 2.3 查询改写的输入

`rewrite_query()` 的输入主要是：

```text
user_query
history
history_summary
```

也就是：

```text
当前用户问题
最近对话
历史摘要
```

这样它可以处理“它、这个、上面那个、刚才说的”等指代问题。

### 2.4 查询改写的输出例子

用户问：

```text
这个多久检查一次？
```

如果历史里上一轮聊的是“制动摩擦块”，查询改写可以输出：

```json
{
  "original_query": "这个多久检查一次？",
  "rewritten_query": "车辆保养时制动摩擦块的检查周期是什么？",
  "keywords": ["制动摩擦块", "保养项目", "保养时间", "20000km"],
  "sub_queries": []
}
```

这里的价值是：

```text
原问题里的“这个”被补全成“制动摩擦块”
rewritten_query 用于向量检索
keywords 用于 BM25 关键词检索
```

### 2.5 和检索链路怎么衔接

查询改写后，检索不是只查一次，而是多路召回。

在 `retriever.py` 里：

```text
original_query
rewritten_query
最多 3 个 sub_queries
```

会走 hybrid 检索，也就是：

```text
Qdrant 向量检索 + 本地 BM25 关键词检索
```

而：

```text
keywords
```

会拼成：

```python
keyword_query = " ".join(keywords)
```

然后单独走一次：

```text
sparse-only BM25 检索
```

最后所有候选 chunk 会通过 RRF 做全局融合。

不同来源的权重是：

```python
RAG_SOURCE_WEIGHT_ORIGINAL_QUERY = 1.3
RAG_SOURCE_WEIGHT_REWRITTEN_QUERY = 1.1
RAG_SOURCE_WEIGHT_SUB_QUERY = 1.0
RAG_SOURCE_WEIGHT_KEYWORDS = 0.8
```

这样设计的含义是：

```text
原问题权重最高，避免改写偏离用户真实意图。
改写问题用于补全语义，提高向量召回。
子问题用于处理多意图问题。
keywords 用于补强专业词、数字、按钮名等精确匹配。
```

### 2.6 失败兜底

如果 LLM 改写失败，代码不会中断检索，而是 fallback 到原问题：

```text
original_query = user_query
rewritten_query = user_query
keywords = []
sub_queries = []
used_llm = False
```

这样即使查询改写服务异常，基础 RAG 检索仍然能工作。

### 2.7 面试表达

可以这样讲：

> 查询改写主要在 `query_rewrite_service.py` 里实现。它的作用不是回答问题，而是把用户的口语问题转换成更适合检索的结构化查询结果。输入包括当前问题、最近对话和历史摘要，输出包括 `original_query`、`rewritten_query`、`keywords` 和 `sub_queries`。比如用户问“这个多久检查一次”，如果历史里“这个”指的是制动摩擦块，改写后会得到“车辆保养时制动摩擦块的检查周期是什么”，同时提取 keywords，比如“制动摩擦块、保养项目、20000km”。检索时，原问题、改写问题和子问题会走 hybrid retrieval，keywords 会单独走 BM25 稀疏检索，最后所有候选 chunk 用 RRF 融合。这样既保留用户原始意图，又能补全上下文指代，还能增强专业词和数字类问题的召回稳定性。如果 LLM 改写失败，系统会 fallback 到原问题，保证检索链路可用。

## 3. 缓存设计

这个项目里的缓存主要分两类：

```text
RAG 检索缓存：减少 embedding、向量检索、BM25 检索的重复计算
认证状态缓存：管理 refresh token 和 access token 黑名单
```

这份文档主要讲 RAG 检索缓存。认证相关的 Redis 使用在 `auth_service.py`，不属于检索主链路。

核心文件：

```text
backend/app/db/redis.py
backend/app/rag/retriever.py
backend/app/rag/sparse_index.py
backend/app/core/config.py
backend/app/services/auth_service.py
```

### 3.1 Redis 客户端怎么初始化

Redis 连接在 `backend/app/db/redis.py` 中管理。

服务启动时会调用：

```python
init_redis()
```

它会根据配置拼出 Redis URL：

```python
redis://{host}:{port}/{db}
```

相关配置在 `config.py`：

```python
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None
REDIS_SOCKET_TIMEOUT = 3.0
```

后端接口通过依赖注入拿到 Redis：

```text
get_redis_client()
```

然后传给聊天、RAG 检索、认证等服务。

### 3.2 RAG 缓存的公共读写函数

RAG 检索里的 Redis 读写封装在 `retriever.py`：

```python
_get_cached_json(redis, key)
_set_cached_json(redis, key, value, ttl)
```

设计特点：

```text
1. value 会用 JSON 序列化保存。
2. 读取失败或写入失败只打 warning，不中断主流程。
3. redis 为 None 时直接跳过缓存。
4. 写入时统一带 TTL，避免缓存长期堆积。
```

也就是说，缓存是“加速层”，不是强依赖。Redis 出问题时，系统仍然可以走实时 embedding 和实时检索，只是会慢一些。

### 3.3 查询 embedding 缓存

第一类 RAG 缓存是 query embedding 缓存。

位置在 `_vector_recall()`：

```python
query_hash = sha256_text(query)
embedding_key = f"rag:query_embedding:{query_hash}"
vector = await _get_cached_json(redis, embedding_key)
```

流程：

```text
用户 query
-> normalize_query
-> sha256 得到 query_hash
-> 查 Redis: rag:query_embedding:{query_hash}
-> 命中：直接拿 vector
-> 未命中：调用 embed_text(query)
-> 把新 vector 写入 Redis
```

TTL 配置：

```python
RAG_QUERY_EMBEDDING_CACHE_TTL = 3600
```

也就是 1 小时。

作用：

```text
避免相同 query 在短时间内重复调用 embedding 服务
降低外部 embedding API 调用成本
减少检索首段耗时
```

例子：

```text
用户连续问两次：“制动摩擦块多久检查一次？”
```

第二次查询时，如果 query 清洗后一致，就可以直接复用 Redis 里的向量，不需要重新请求 embedding 模型。

### 3.4 检索结果缓存

第二类 RAG 缓存是 retrieval results 缓存。

普通检索入口是：

```python
retrieve_chunks()
```

缓存 key 形态：

```text
rag:retrieval:{strategy}:seed-only:{query_hash}:{source_file}:{top_k}
```

其中：

| 字段 | 含义 |
| --- | --- |
| `strategy` | 当前检索策略，例如 `vector` 或 `hybrid`。 |
| `query_hash` | 清洗后 query 的 sha256。 |
| `source_file` | 手册过滤条件，没有则是 `all`。 |
| `top_k` | 本次检索数量。 |

流程：

```text
进入 retrieve_chunks()
-> 根据 query、source_file、top_k 生成 retrieval_key
-> 查 Redis
-> 命中：直接反序列化成 RetrievedChunk 返回
-> 未命中：执行 vector 或 hybrid 检索
-> 把检索结果写入 Redis
```

TTL 配置：

```python
RAG_RETRIEVAL_CACHE_TTL = 600
```

也就是 10 分钟。

作用：

```text
避免相同问题短时间内重复跑 Qdrant 检索和 BM25 检索
减少 Redis 之外的外部服务请求
提高高频问题或重复评估时的响应速度
```

例子：

```text
query = "制动摩擦块多久检查一次"
source_file = "xia.pdf"
top_k = 5
strategy = "hybrid"
```

缓存 key 会包含这些条件。只要其中一个变了，例如用户切换到 `han.pdf`，或者 `top_k` 从 5 变成 10，就不会误用旧缓存。

### 3.5 sparse-only 检索缓存

keywords 会单独走 sparse-only 检索：

```python
retrieve_sparse_chunks()
```

缓存 key 形态：

```text
rag:retrieval:sparse-only:seed-only:{query_hash}:{source_file}:{top_k}
```

它主要缓存：

```text
keywords 拼成的 keyword_query 的 BM25 检索结果
```

例如：

```text
keyword_query = "制动摩擦块 保养项目 20000km"
```

第一次会走本地 BM25 计算，之后 10 分钟内相同 keyword query 可以直接返回缓存结果。

### 3.6 进程内 sparse index 缓存

除了 Redis，项目里还有一个进程内缓存：

```python
@lru_cache(maxsize=1)
def get_sparse_index() -> SparseChunkIndex:
    return SparseChunkIndex(Path(settings.RAG_CHUNKS_JSONL_PATH))
```

这表示：

```text
SparseChunkIndex 只在当前 Python 进程内构建一次
后续关键词检索复用同一个内存倒排索引
```

作用：

```text
避免每次 BM25 检索都重新读取 chunks.jsonl
避免重复构建倒排索引
让关键词检索变成内存查询
```

需要注意：

```text
如果 chunks.jsonl 更新了，当前进程里的 sparse index 不会自动刷新。
需要重启后端服务，或者后续增加显式 reload 机制。
```

这个缓存和 Redis 不一样：

```text
Redis 缓存的是查询结果和 query embedding。
lru_cache 缓存的是倒排索引对象本身。
```

### 3.7 认证相关 Redis 缓存

项目里 Redis 还用于认证状态管理。

登录时保存 refresh token 状态：

```text
auth:refresh:{user_id}:{jti}
```

退出登录时写入 access token 黑名单：

```text
auth:blacklist:{jti}
```

作用：

```text
支持 refresh token 轮换和撤销
支持 logout 后让未过期 access token 失效
```

这部分和 RAG 检索缓存无关，但说明 Redis 在项目里不只承担检索加速，也承担短期认证状态管理。

### 3.8 缓存的整体作用

整体看，缓存主要解决三个问题：

```text
1. 降低延迟
   相同 query 不重复生成 embedding，不重复跑检索。

2. 降低成本
   embedding 服务通常是外部模型调用，缓存可以减少重复请求。

3. 提高系统稳定性
   Redis 缓存读写失败不会中断主流程，属于可降级加速层。
```

在这个项目里，RAG 一次聊天请求大致会经过：

```text
query rewrite
-> 多路 retrieve_chunks / retrieve_sparse_chunks
-> query embedding cache
-> retrieval result cache
-> sparse index lru_cache
-> Qdrant / BM25
-> RRF 融合
-> 上下文扩展
-> LLM 回答
```

缓存主要覆盖的是：

```text
embedding 结果
检索结果
BM25 倒排索引对象
```

### 3.9 面试表达

可以这样讲：

> 项目里的缓存主要分为 Redis 缓存和进程内缓存。Redis 在 RAG 检索里缓存两类东西：第一类是 query embedding，key 是 `rag:query_embedding:{query_hash}`，TTL 是 1 小时，用来避免相同问题重复调用 embedding 服务；第二类是检索结果缓存，key 里包含检索策略、query hash、source_file 和 top_k，TTL 是 10 分钟，用来避免短时间内相同问题重复跑 Qdrant 和 BM25。关键词检索还有一个进程内缓存，`get_sparse_index()` 用 `lru_cache(maxsize=1)` 缓存从 `chunks.jsonl` 构建出来的 BM25 倒排索引，避免每次检索都重新读文件和建索引。缓存读写失败只会打 warning，不会中断主流程，所以它是一个可降级的加速层。Redis 另外也用于认证，比如 refresh token 状态和 access token 黑名单，但这部分不属于 RAG 检索链路。
