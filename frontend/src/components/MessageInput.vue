<script setup lang="ts">
import { ref } from "vue";

defineProps<{
  disabled: boolean;
  streaming: boolean;
}>();

const emit = defineEmits<{
  send: [message: string];
}>();

const draft = ref("");

function submit() {
  const message = draft.value.trim();
  if (!message) return;
  emit("send", message);
  draft.value = "";
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submit();
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <textarea
      v-model="draft"
      :disabled="disabled"
      placeholder="输入你的手册问题"
      rows="3"
      @keydown="handleKeydown"
    />
    <button class="primary" :disabled="disabled || !draft.trim()" type="submit">
      {{ streaming ? "生成中" : "发送" }}
    </button>
  </form>
</template>
