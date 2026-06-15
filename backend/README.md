# Car Manual RAG Backend

## Start

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Swagger UI: http://127.0.0.1:8000/docs

Health check: http://127.0.0.1:8000/health

## Streaming Chat

Configure `DASHSCOPE_API_KEY` or `LLM_API_KEY` in `.env`, then call:

```http
POST /api/v1/chat/stream
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "conversation_id": 1,
  "message": "你好",
  "stream": true
}
```

The endpoint returns Server-Sent Events:

- `start`: user message is saved
- `delta`: generated content chunk
- `done`: full assistant reply is saved
- `error`: stream failed and failure is recorded




