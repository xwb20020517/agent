import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";
import ChatView from "../views/ChatView.vue";
import LoginView from "../views/LoginView.vue";
import RegisterView from "../views/RegisterView.vue";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/chat" },
    { path: "/login", component: LoginView },
    { path: "/register", component: RegisterView },
    { path: "/chat", component: ChatView, meta: { requiresAuth: true } },
  ],
});

router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.requiresAuth && !auth.isAuthed) {
    return "/login";
  }
  if ((to.path === "/login" || to.path === "/register") && auth.isAuthed) {
    return "/chat";
  }
});
