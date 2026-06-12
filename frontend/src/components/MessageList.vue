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
    </article>
  </div>
</template>
