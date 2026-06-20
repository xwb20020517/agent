<script setup lang="ts">
import MessageInput from "./MessageInput.vue";
import MessageList from "./MessageList.vue";
import { useChatStore } from "../stores/chat";

const chat = useChatStore();
</script>

<template>
  <section class="chat-panel">
    <header class="chat-header">
      <div>
        <h1>{{ chat.currentConversation?.title ?? "开始一次问答" }}</h1>
        <span>{{ chat.streaming ? "生成中" : "就绪" }}</span>
      </div>
      <label class="manual-picker">
        <span>手册</span>
        <select v-model="chat.selectedSourceFile" :disabled="chat.streaming || !chat.documents.length">
          <option value="">全部手册</option>
          <option v-for="doc in chat.documents" :key="doc.id" :value="doc.source_file">
            {{ doc.display_name ?? doc.source_file }}
          </option>
        </select>
      </label>
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
