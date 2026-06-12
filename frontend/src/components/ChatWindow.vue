<script setup lang="ts">
import MessageInput from "./MessageInput.vue";
import MessageList from "./MessageList.vue";
import { useChatStore } from "../stores/chat";

const chat = useChatStore();
</script>

<template>
  <section class="chat-panel">
    <header class="chat-header">
      <h1>{{ chat.currentConversation?.title ?? "开始一次问答" }}</h1>
      <span>{{ chat.streaming ? "生成中" : "就绪" }}</span>
    </header>

    <MessageList :messages="chat.messages" :loading="chat.loading" />
    <p v-if="chat.error" class="error">{{ chat.error }}</p>
    <MessageInput
      :disabled="chat.streaming"
      :streaming="chat.streaming"
      @send="chat.sendMessage"
    />
  </section>
</template>
