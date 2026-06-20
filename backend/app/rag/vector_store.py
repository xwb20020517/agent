import asyncio
import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from fastapi import status
from loguru import logger

from app.core.config import settings
from app.core.exceptions import AppException


@dataclass(frozen=True)
class VectorSearchResult:
    id: str
    score: float
    payload: dict[str, Any]


class QdrantVectorStore:
    def __init__(self, collection_name: str | None = None) -> None:
        self.collection_name = collection_name or settings.QDRANT_COLLECTION

    def _url(self, path: str) -> str:
        return urljoin(settings.QDRANT_URL.rstrip("/") + "/", path.lstrip("/"))

    def _request_sync(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if settings.QDRANT_API_KEY:
            headers["api-key"] = settings.QDRANT_API_KEY
        request = Request(self._url(path), data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise AppException(
                "Qdrant request failed",
                code=50220,
                status_code=status.HTTP_502_BAD_GATEWAY,
                data={"status": exc.code, "detail": detail[:1000]},
            ) from exc
        except URLError as exc:
            raise AppException(
                "Qdrant connection failed",
                code=50221,
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._request_sync, method, path, payload)

    async def ensure_collection(self) -> None:
        encoded_name = quote(self.collection_name, safe="")
        try:
            await self._request("GET", f"/collections/{encoded_name}")
            return
        except AppException as exc:
            status_detail = exc.data or {}
            if status_detail.get("status") != 404:
                raise

        await self._request(
            "PUT",
            f"/collections/{encoded_name}",
            {
                "vectors": {
                    "size": settings.EMBEDDING_DIM,
                    "distance": "Cosine",
                }
            },
        )
        logger.info("Created Qdrant collection {}", self.collection_name)

    async def upsert_points(self, points: list[dict[str, Any]]) -> None:
        if not points:
            return
        await self.ensure_collection()
        encoded_name = quote(self.collection_name, safe="")
        await self._request(
            "PUT",
            f"/collections/{encoded_name}/points?wait=true",
            {"points": points},
        )
        logger.info("Upserted {} Qdrant points into {}", len(points), self.collection_name)

    async def search(
        self,
        vector: list[float],
        *,
        top_k: int,
        source_file: str | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        await self.ensure_collection()
        encoded_name = quote(self.collection_name, safe="")
        payload: dict[str, Any] = {
            "vector": vector,
            "limit": top_k,
            "with_payload": True,
        }
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        if source_file:
            payload["filter"] = {"must": [{"key": "source_file", "match": {"value": source_file}}]}

        response = await self._request("POST", f"/collections/{encoded_name}/points/search", payload)
        return [
            VectorSearchResult(
                id=str(item.get("id")),
                score=float(item.get("score", 0.0)),
                payload=dict(item.get("payload") or {}),
            )
            for item in response.get("result", [])
        ]
