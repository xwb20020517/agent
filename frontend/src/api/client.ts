const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T;
  request_id: string | null;
};

export class ApiError extends Error {
  status: number;
  code: number;

  constructor(message: string, status: number, code: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export type User = {
  id: number;
  username: string;
  email: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  updated_at: string;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
};

export type Conversation = {
  id: number;
  user_id: number;
  title: string;
  model_name: string | null;
  system_prompt: string | null;
  is_deleted: boolean;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: number;
  conversation_id: number;
  user_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  status: "success" | "streaming" | "failed";
  token_count: number | null;
  latency_ms: number | null;
  created_at: string;
};

export type LocalMessage = Pick<Message, "role" | "content" | "status"> & {
  id: number | string;
};

export type ConversationDetail = Conversation & {
  messages: Message[];
};

async function request<T>(path: string, options: RequestInit = {}, token?: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const payload = (await response.json().catch(() => null)) as ApiResponse<T> | null;
  if (!response.ok || !payload || payload.code !== 0) {
    throw new ApiError(payload?.message || "Request failed", response.status, payload?.code ?? -1);
  }
  return payload.data;
}

export function register(username: string, password: string, email?: string) {
  return request<User>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password, email: email || null }),
  });
}

export function login(username: string, password: string) {
  return request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function refreshToken(refreshToken: string) {
  return request<TokenResponse>("/api/v1/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function logout(token: string) {
  return request<{ logged_out: boolean }>("/api/v1/auth/logout", { method: "POST" }, token);
}

export function getCurrentUser(token: string) {
  return request<User>("/api/v1/users/me", {}, token);
}

export function listConversations(token: string) {
  return request<Conversation[]>("/api/v1/conversations", {}, token);
}

export function createConversation(token: string, title = "New conversation") {
  return request<Conversation>(
    "/api/v1/conversations",
    {
      method: "POST",
      body: JSON.stringify({ title }),
    },
    token,
  );
}

export function getConversation(token: string, conversationId: number) {
  return request<ConversationDetail>(`/api/v1/conversations/${conversationId}`, {}, token);
}

export function renameConversation(token: string, conversationId: number, title: string) {
  return request<Conversation>(
    `/api/v1/conversations/${conversationId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
    token,
  );
}

export function deleteConversation(token: string, conversationId: number) {
  return request<{ deleted: boolean }>(
    `/api/v1/conversations/${conversationId}`,
    { method: "DELETE" },
    token,
  );
}

export type StreamEvent =
  | { event: "start"; data: { conversation_id: number; user_message_id: number; request_id: string } }
  | { event: "delta"; data: { content: string } }
  | {
      event: "done";
      data: {
        conversation_id: number;
        user_message_id: number;
        assistant_message_id: number;
        answer: string;
      };
    }
  | { event: "error"; data: { message: string; assistant_message_id?: number } };

function parseSseBlock(block: string): StreamEvent | null {
  const lines = block.split(/\r?\n/);
  const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
  const data = lines
    .filter((line) => line.startsWith("data: "))
    .map((line) => line.slice(6))
    .join("\n");
  if (!event || !data) return null;
  return { event, data: JSON.parse(data) } as StreamEvent;
}

export async function streamChat(
  token: string,
  conversationId: number,
  message: string,
  onEvent: (event: StreamEvent) => void,
) {
  const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ conversation_id: conversationId, message, stream: true }),
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null);
    throw new ApiError(payload?.message || "Stream request failed", response.status, payload?.code ?? -1);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = parseSseBlock(block.trim());
      if (event) onEvent(event);
    }
  }

  if (buffer.trim()) {
    const event = parseSseBlock(buffer.trim());
    if (event) onEvent(event);
  }
}
