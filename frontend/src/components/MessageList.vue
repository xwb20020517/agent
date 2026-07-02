<script setup lang="ts">
import type { LocalMessage, RagSource } from "../api/client";

defineProps<{
  messages: LocalMessage[];
  loading: boolean;
}>();

const visibleSourceCount = 8;

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function formatPageRange(source: RagSource) {
  const start = source.page_number_start ?? source.page_number_end;
  const end = source.page_number_end;
  if (!start) return "";
  if (end && end !== start) return `页码 ${start}-${end}`;
  return `页码 ${start}`;
}

function sourceLabel(source: RagSource) {
  return [source.source_file, source.section_title, formatPageRange(source)].filter(Boolean).join(" / ");
}

function sourceIntro(source: RagSource) {
  return normalizeText(source.content_preview);
}

function sourceFullText(source: RagSource) {
  return `${sourceLabel(source)}\n\n${sourceIntro(source)}`;
}
</script>

<template>
  <div class="messages">
    <div v-if="loading" class="empty loading-state">
      <span class="spinner" aria-hidden="true"></span>
      <span>正在加载消息</span>
    </div>
    <p v-else-if="!messages.length" class="empty">选择或创建会话后，输入问题即可开始。</p>
    <article v-for="item in messages" :key="item.id" :class="['message', item.role, item.status]">
      <div class="role">{{ item.role === "user" ? "我" : item.role === "assistant" ? "助手" : "系统" }}</div>
      <div v-if="item.status === 'streaming' && !item.content" class="typing-indicator" aria-live="polite">
        <span class="spinner" aria-hidden="true"></span>
        <span>等待模型回复</span>
      </div>
      <p v-else>{{ item.content }}</p>
      <div v-if="item.sources?.length" class="sources">
        <div class="sources-header">
          <strong>引用来源</strong>
          <span>{{ Math.min(item.sources.length, visibleSourceCount) }} / {{ item.sources.length }}</span>
        </div>
        <ol>
          <li
            v-for="source in item.sources.slice(0, visibleSourceCount)"
            :key="source.chunk_id"
            class="source-line"
            tabindex="0"
          >
            <div class="source-row" :title="sourceFullText(source)">
              <span class="source-label">{{ sourceLabel(source) }}</span>
              <span class="source-snippet">{{ sourceIntro(source) }}</span>
            </div>
            <div class="source-popover" role="tooltip">
              {{ sourceFullText(source) }}
            </div>
          </li>
        </ol>
      </div>
    </article>
  </div>
</template>
