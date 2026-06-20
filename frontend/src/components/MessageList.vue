<script setup lang="ts">
import type { LocalMessage } from "../api/client";

defineProps<{
  messages: LocalMessage[];
  loading: boolean;
}>();
</script>

<template>
  <div class="messages">
    <p v-if="loading" class="empty">正在加载消息</p>
    <p v-else-if="!messages.length" class="empty">选择或创建会话后，输入问题即可开始。</p>
    <article v-for="item in messages" :key="item.id" :class="['message', item.role, item.status]">
      <div class="role">{{ item.role === "user" ? "我" : item.role === "assistant" ? "助手" : "系统" }}</div>
      <p>{{ item.content || (item.status === "streaming" ? "..." : "") }}</p>
      <div v-if="item.sources?.length" class="sources">
        <strong>引用来源</strong>
        <ul>
          <li v-for="source in item.sources" :key="source.chunk_id">
            <div class="source-meta">
              <span>{{ source.source_file }}</span>
              <span v-if="source.section_title">｜{{ source.section_title }}</span>
              <span v-if="source.page_number_start || source.page_number_end">
                ｜页码 {{ source.page_number_start ?? source.page_number_end }}
                <template v-if="source.page_number_end && source.page_number_end !== source.page_number_start">
                  -{{ source.page_number_end }}
                </template>
              </span>
              <small>score {{ source.score.toFixed(3) }}</small>
            </div>
            <p>{{ source.content_preview }}</p>
          </li>
        </ul>
      </div>
    </article>
  </div>
</template>
