<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";

const auth = useAuthStore();
const router = useRouter();
const username = ref("");
const email = ref("");
const password = ref("");

async function submit() {
  await auth.register(username.value, password.value, email.value);
  await router.push("/chat");
}
</script>

<template>
  <main class="auth-page">
    <form class="auth-card" @submit.prevent="submit">
      <div>
        <h1>注册</h1>
        <p>创建账号后开始保存会话和消息历史</p>
      </div>
      <label>
        用户名
        <input v-model="username" autocomplete="username" required />
      </label>
      <label>
        邮箱
        <input v-model="email" autocomplete="email" type="email" />
      </label>
      <label>
        密码
        <input v-model="password" autocomplete="new-password" required type="password" />
      </label>
      <p v-if="auth.error" class="error">{{ auth.error }}</p>
      <button class="primary wide" :disabled="auth.loading" type="submit">
        {{ auth.loading ? "注册中" : "注册并登录" }}
      </button>
      <RouterLink class="text-link" to="/login">已有账号，去登录</RouterLink>
    </form>
  </main>
</template>
