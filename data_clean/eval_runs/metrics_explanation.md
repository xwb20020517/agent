# RAG 评估指标说明

这份说明主要整理当前评估里常看的几个指标：`chunk_hit_rate`、`chunk_recall`、`chunk_precision`、`context_recall`、`context_precision`。它们都是用来判断 RAG 检索质量的，但关注点不同。

## 1. Chunk 指标

Chunk 指标看的是：**检索出来的 chunk_id 和人工标注的标准 chunk_id 是否匹配**。

评估时通常会有两组数据：

```text
gold_chunk_ids      人工标注的标准证据 chunk
retrieved_chunk_ids 系统检索出来的 chunk
```

### 1.1 chunk_hit_rate

`chunk_hit_rate` 看的是：**每个问题有没有至少命中一个正确 chunk**。

单条 case 的判断：

```text
只要 retrieved_chunk_ids 里有一个出现在 gold_chunk_ids 中
这个 case 就算 chunk_hit = true
```

整体指标：

```text
chunk_hit_rate = chunk_hit 为 true 的 case 数 / 总成功 case 数
```

例子：

```text
gold = [A, B]
retrieved = [A, X, Y]
```

因为命中了 `A`，所以这条 case 算命中。

它关注的是：

```text
这个问题有没有找到至少一块正确证据。
```

### 1.2 chunk_recall

`chunk_recall` 看的是：**标准 chunk 被找回了多少**。

计算方式：

```text
chunk_recall = 命中的标准 chunk 数 / 标准 chunk 总数
```

例子：

```text
gold = [A, B, C]
retrieved = [A, C, X]
```

命中了 `A`、`C`，所以：

```text
chunk_recall = 2 / 3
```

它关注的是：

```text
标准证据有没有被找全。
```

### 1.3 chunk_precision

`chunk_precision` 看的是：**检索结果里有多少是真的正确 chunk**。

计算方式：

```text
chunk_precision = 命中的标准 chunk 数 / 检索出来的 chunk 总数
```

例子：

```text
gold = [A, B]
retrieved = [A, X, Y, Z]
```

命中了 1 个，检索出来 4 个，所以：

```text
chunk_precision = 1 / 4
```

它关注的是：

```text
检索结果干不干净，噪声多不多。
```

### 1.4 三个 Chunk 指标的区别

最简单的记法：

```text
chunk_hit_rate：有没有找到
chunk_recall：该找的找全了吗
chunk_precision：找出来的有多少是真的
```

完整例子：

```text
gold = [A, B]
retrieved = [A, C, D, E]
```

结果：

```text
chunk_hit = true
chunk_recall = 1 / 2 = 0.5
chunk_precision = 1 / 4 = 0.25
```

说明：系统找到了一个正确 chunk，但标准证据没找全，而且检索结果里噪声较多。

## 2. Context 指标

Context 指标看的是：**检索回来的文本内容是否覆盖了标准证据**。

它和 Chunk 指标的区别是：

```text
Chunk 指标：看 chunk_id 是否命中
Context 指标：看 chunk 内容是否覆盖证据文本
```

所以，即使 `chunk_id` 没有完全命中，只要检索出来的内容包含了标准证据，`context_recall` 也可能较高。

## 3. 标准参考文本

Context 指标需要一段标准参考文本。当前逻辑是：

```text
gold_reference = gold_evidence if gold_evidence else gold_answer
```

也就是：

1. 优先使用人工标注的 `gold_evidence`。
2. 如果没有 `gold_evidence`，再使用 `gold_answer`。

## 4. context_recall

`context_recall` 看的是：**标准证据里的信息，有多少被检索上下文覆盖到了**。

做法：

```text
retrieved_context = top-k chunks 的 content 拼接结果
context_recall = char_recall(retrieved_context, gold_reference)
```

`char_recall` 是字符级覆盖率：

```text
context_recall = 检索上下文和标准证据的重叠字符数 / 标准证据字符数
```

它回答的问题是：

```text
该有的证据，检索上下文里有没有覆盖到？
```

如果标准证据中的关键信息大部分都出现在检索上下文里，`context_recall` 就会比较高。

## 5. context_precision

`context_precision` 看的是：**覆盖标准证据的 chunk 是否排在前面**。

它不是直接看所有上下文拼接结果，而是逐个 chunk 算相关性：

```text
score_i = char_recall(chunk_i.content, gold_reference)
```

然后用阈值判断某个 chunk 是否相关：

```text
score_i >= context_relevance_threshold
```

当前默认阈值是：

```text
context_relevance_threshold = 0.35
```

接着按检索排名计算类似 Average Precision 的分数：

```text
从第 1 个 chunk 往后遍历：

如果当前 chunk 相关：
    relevant_seen += 1
    precision_sum += relevant_seen / 当前排名

context_precision = precision_sum / relevant_seen
```

如果没有任何 chunk 达到相关阈值：

```text
context_precision = 0
```

例子：

```text
context_relevance_scores = [0.8, 0.1, 0.6, 0.0, 0.4]
threshold = 0.35
```

第 1、3、5 个 chunk 被认为相关。

计算过程：

```text
rank=1: precision = 1 / 1
rank=3: precision = 2 / 3
rank=5: precision = 3 / 5

context_precision = (1/1 + 2/3 + 3/5) / 3
```

它关注的是：

```text
相关证据是否排在前面。
```

## 6. Context 指标的特点

优点：

- 不依赖 LLM judge，计算快。
- 能补充 chunk_id 指标的不足。
- 即使标准 chunk 没完全命中，也能判断内容是否覆盖到了答案证据。

局限：

- 当前是字符级覆盖，不是真正的语义理解。
- 同义改写、概括表达可能得分偏低。
- 重复字符或长文本可能影响覆盖率判断。
- 不能像 LLM judge 那样判断事实支持、幻觉、答案正确性。

## 7. 面试表达

可以这样讲：

> 我们的检索评估分两层。第一层是 chunk 级指标，看检索出来的 chunk_id 和人工标注的 gold_chunk_ids 是否匹配。其中 chunk_hit_rate 看有没有至少命中一个正确 chunk，chunk_recall 看标准 chunk 找回了多少，chunk_precision 看检索结果里有多少是真的正确 chunk。第二层是 context 级指标，不只看 ID，而是看检索回来的文本内容是否覆盖 gold_evidence。context_recall 把 top-k chunk 内容拼起来，计算对标准证据的字符级覆盖率；context_precision 则逐个 chunk 计算和标准证据的覆盖分数，用阈值判断相关 chunk，再看相关 chunk 是否排在前面。这样可以同时评估检索是否找到了正确证据，以及返回上下文的内容质量和排序质量。

