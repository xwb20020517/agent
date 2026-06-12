<script setup lang="ts">
import { ref } from "vue";
import { useChatStore } from "../stores/chat";

defineProps<{
  username?: string;
}>();

const emit = defineEmits<{
  logout: [];
}>();

const chat = useChatStore();
const editingTitle = ref("");

async function renameCurrent() {
  const title = editingTitle.value.trim();
  if (!title) return;
  await chat.renameCurrentConversation(title);
  editingTitle.value = "";
}

function beginRename() {
  editingTitle.value = chat.currentConversation?.title ?? "";
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <strong>车型手册问答</strong>
      <button class="ghost" type="button" @click="emit('logout')">退出</button>
    </div>

    <div class="account-row">
      <span>{{ username ?? "当前用户" }}</span>
    </div>

    <button class="primary wide" type="button" @click="chat.createNewConversation">新建会话</button>

    <div class="sidebar-actions">
      <input
        v-model="editingTitle"
        :placeholder="chat.currentConversation ? '新的会话标题' : '选择会话后重命名'"
        :disabled="!chat.currentConversation"
        @focus="beginRename"
      />
      <button class="ghost" :disabled="!chat.currentConversation || !editingTitle.trim()" type="button" @click="renameCurrent">
        重命名
      </button>
      <button class="danger" :disabled="!chat.currentConversation" type="button" @click="chat.deleteCurrentConversation">
        删除
      </button>
    </div>

    <nav class="conversation-list">
      <button
        v-for="item in chat.conversations"
        :key="item.id"
        :class="{ selected: item.id === chat.currentConversationId }"
        type="button"
        @click="chat.selectConversation(item.id)"
      >
        <span>{{ item.title }}</span>
        <small>{{ item.model_name ?? "未调用模型" }}</small>
      </button>
    </nav>
  </aside>
</template>
