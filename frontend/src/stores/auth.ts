import { defineStore } from "pinia";
import { computed, ref } from "vue";
import * as api from "../api/client";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem("access_token") ?? "");
  const refreshToken = ref(localStorage.getItem("refresh_token") ?? "");
  const user = ref<api.User | null>(null);
  const loading = ref(false);
  const error = ref("");
  let refreshPromise: Promise<string> | null = null;

  const isAuthed = computed(() => Boolean(token.value));

  function setTokens(tokens: api.TokenResponse) {
    token.value = tokens.access_token;
    refreshToken.value = tokens.refresh_token;
    localStorage.setItem("access_token", tokens.access_token);
    localStorage.setItem("refresh_token", tokens.refresh_token);
  }

  async function login(username: string, password: string) {
    error.value = "";
    loading.value = true;
    try {
      const tokens = await api.login(username, password);
      setTokens(tokens);
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
      setTokens(tokens);
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
      user.value = await requestWithRefresh((accessToken) => api.getCurrentUser(accessToken));
    } catch {
      clearAuth();
    }
  }

  async function refreshAccessToken() {
    if (!refreshToken.value) {
      clearAuth();
      throw new Error("Authentication expired");
    }

    refreshPromise ??= api
      .refreshToken(refreshToken.value)
      .then((tokens) => {
        setTokens(tokens);
        return tokens.access_token;
      })
      .catch((err) => {
        clearAuth();
        throw err;
      })
      .finally(() => {
        refreshPromise = null;
      });

    return refreshPromise;
  }

  async function requestWithRefresh<T>(requester: (accessToken: string) => Promise<T>) {
    if (!token.value) throw new Error("Authentication required");
    try {
      return await requester(token.value);
    } catch (err) {
      if (!(err instanceof api.ApiError) || err.status !== 401) {
        throw err;
      }
      const nextToken = await refreshAccessToken();
      return requester(nextToken);
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
    refreshToken.value = "";
    user.value = null;
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
  }

  return {
    token,
    refreshToken,
    user,
    loading,
    error,
    isAuthed,
    login,
    register,
    loadCurrentUser,
    refreshAccessToken,
    requestWithRefresh,
    logout,
  };
});
