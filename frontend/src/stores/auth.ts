import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as api from "../api/client";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem("access_token") ?? "");
  const user = ref<api.User | null>(null);
  const loading = ref(false);
  const error = ref("");

  const isAuthed = computed(() => Boolean(token.value));

  function setToken(nextToken: string) {
    token.value = nextToken;
    localStorage.setItem("access_token", nextToken);
  }

  async function login(username: string, password: string) {
    error.value = "";
    loading.value = true;
    try {
      const tokens = await api.login(username, password);
      setToken(tokens.access_token);
      user.value = await api.getCurrentUser(tokens.access_token);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Login failed";
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function register(username: string, password: string, email?: string) {
    error.value = "";
    loading.value = true;
    try {
      await api.register(username, password, email);
      const tokens = await api.login(username, password);
      setToken(tokens.access_token);
      user.value = await api.getCurrentUser(tokens.access_token);
    } catch (err) {
      error.value = err instanceof Error ? err.message : "Register failed";
      throw err;
    } finally {
      loading.value = false;
    }
  }

  async function loadCurrentUser() {
    if (!token.value) return;
    try {
      user.value = await api.getCurrentUser(token.value);
    } catch {
      clearAuth();
    }
  }

  async function logout() {
    if (token.value) {
      await api.logout(token.value).catch(() => undefined);
    }
    clearAuth();
  }

  function clearAuth() {
    token.value = "";
    user.value = null;
    localStorage.removeItem("access_token");
  }

  return {
    token,
    user,
    loading,
    error,
    isAuthed,
    login,
    register,
    loadCurrentUser,
    logout,
  };
});
