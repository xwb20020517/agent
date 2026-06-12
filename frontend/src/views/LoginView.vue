<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const username = ref("");
const password = ref("");

async function submit() {
  await auth.login(username.value, password.value);
  await router.push("/chat");
}
</script>

<template>
  <main class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <div>
        <h1>登录</h1>
        <p>进入车型用户手册智能问答系统</p>
      </div>
      <label>
        用户名
        <input v-model="username" autocomplete="username" required />
      </label>
      <label>
        密码
        <input v-model="password" autocomplete="current-password" required type="password" />
      </label>
      <p v-if="auth.error" class="error">{{ auth.error }}</p>
      <button class="primary wide" :disabled="auth.loading" type="submit">
        {{ auth.loading ? "登录中" : "登录" }}
      </button>
      <RouterLink class="text-link" to="/register">创建账号</RouterLink>
    </form>
  </main>
</template>
