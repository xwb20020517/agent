import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as api from "../api/client";
import { useAuthStore } from "./auth";

export const useChatStore = defineStore("chat", () => {
  const conversations = ref<api.Conversation[]>([]);
  const currentConversationId = ref<number | null>(null);
  const messages = ref<api.LocalMessage[]>([]);
  const loading = ref(false);
  const streaming = ref(false);
  const error = ref("");

  const currentConversation = computed(() =>
    conversations.value.find((item) => item.id === currentConversationId.value) ?? null,
  );

  function requireToken() {
    const auth = useAuthStore();
    if (!auth.token) throw new Error("Authentication required");
    return auth.token;
  }

  async function loadConversations() {
    const auth = useAuthStore();
    conversations.value = await auth.requestWithRefresh((token) => api.listConversations(token));
    if (!currentConversationId.value && conversations.value.length > 0) {
      await selectConversation(conversations.value[0].id);
    }
  }

  async function createNewConversation() {
    const auth = useAuthStore();
    const conversation = await auth.requestWithRefresh((token) => api.createConversation(token));
    conversations.value = [conversation, ...conversations.value];
    await selectConversation(conversation.id);
  }

  async function selectConversation(conversationId: number) {
    const auth = useAuthStore();
    loading.value = true;
    error.value = "";
    try {
      currentConversationId.value = conversationId;
      const detail = await auth.requestWithRefresh((token) => api.getConversation(token, conversationId));
      messages.value = detail.messages.map((item) => ({
        id: item.id,
        role: item.role,
        content: item.content,
        status: item.status,
      }));
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Failed to load conversation";
    } finally {
      loading.value = false;
    }
  }

  async function renameCurrentConversation(title: string) {
    const auth = useAuthStore();
    if (!currentConversationId.value) return;
    const updated = await auth.requestWithRefresh((token) =>
      api.renameConversation(token, currentConversationId.value!, title),
    );
    conversations.value = conversations.value.map((item) => (item.id === updated.id ? updated : item));
  }

  async function deleteCurrentConversation() {
    const auth = useAuthStore();
    if (!currentConversationId.value) return;
    const deletingId = currentConversationId.value;
    await auth.requestWithRefresh((token) => api.deleteConversation(token, deletingId));
    conversations.value = await auth.requestWithRefresh((token) => api.listConversations(token));
    currentConversationId.value = null;
    messages.value = [];
    if (conversations.value.length > 0) {
      await selectConversation(conversations.value[0].id);
    }
  }

  async function sendMessage(content: string) {
    const auth = useAuthStore();
    requireToken();
    const trimmed = content.trim();
    if (!trimmed || streaming.value) return;

    if (!currentConversationId.value) {
      await createNewConversation();
    }
    if (!currentConversationId.value) return;

    const assistantId = `stream-${Date.now()}`;
    messages.value.push({
      id: `user-${Date.now()}`,
      role: "user",
      content: trimmed,
      status: "success",
    });
    messages.value.push({
      id: assistantId,
      role: "assistant",
      content: "",
      status: "streaming",
    });

    error.value = "";
    streaming.value = true;

    try {
      await auth.requestWithRefresh((token) =>
        api.streamChat(token, currentConversationId.value!, trimmed, (event) => {
          const assistant = messages.value.find((item) => item.id === assistantId);
          if (!assistant) return;

          if (event.event === "delta") {
            assistant.content += event.data.content;
          }
          if (event.event === "done") {
            assistant.id = event.data.assistant_message_id;
            assistant.content = event.data.answer;
            assistant.status = "success";
          }
          if (event.event === "error") {
            assistant.id = event.data.assistant_message_id ?? assistant.id;
            assistant.status = "failed";
            error.value = event.data.message;
          }
        }),
      );
      await loadConversations();
    } catch (err) {
      const assistant = messages.value.find((item) => item.id === assistantId);
      if (assistant) assistant.status = "failed";
      error.value = err instanceof Error ? err.message : "Stream failed";
    } finally {
      streaming.value = false;
    }
  }

  function reset() {
    conversations.value = [];
    currentConversationId.value = null;
    messages.value = [];
    loading.value = false;
    streaming.value = false;
    error.value = "";
  }

  return {
    conversations,
    currentConversationId,
    currentConversation,
    messages,
    loading,
    streaming,
    error,
    loadConversations,
    createNewConversation,
    selectConversation,
    renameCurrentConversation,
    deleteCurrentConversation,
    sendMessage,
    reset,
  };
});
