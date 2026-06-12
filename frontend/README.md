# Car Manual RAG Frontend

## Start

```bash
npm install
npm run dev
```

Open http://127.0.0.1:5173

The chat page uses `fetch` to read `POST /api/v1/chat/stream` as SSE, appends `delta` chunks while the model is generating, then replaces the temporary assistant message with the final `done.answer`.
