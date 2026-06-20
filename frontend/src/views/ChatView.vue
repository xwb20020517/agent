<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";
import ConversationSidebar from "../components/ConversationSidebar.vue";
import ChatWindow from "../components/ChatWindow.vue";
import { useAuthStore } from "../stores/auth";
import { useChatStore } from "../stores/chat";

const auth = useAuthStore();
const chat = useChatStore();
const router = useRouter();

async function logout() {
  await auth.logout();
  chat.reset();
  await router.replace("/login");
}

onMounted(async () => {
  await auth.loadCurrentUser();
  if (!auth.isAuthed) {
    await router.replace("/login");
    return;
  }
  await Promise.all([chat.loadConversations(), chat.loadDocuments()]);
});
</script>

<template>
  <main class="app-shell">
    <ConversationSidebar :username="auth.user?.username" @logout="logout" />
    <ChatWindow />
  </main>
</template>
