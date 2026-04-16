from __future__ import annotations

import json

import httpx

from methods.config.settings import settings


def _strip_openai_suffix(base_url: str) -> str:
    if base_url.endswith("/v1"):
        return base_url[:-3]
    return base_url


def embedding_is_configured() -> bool:
    if not settings.embedding_model:
        return False
    if settings.embedding_provider in {"ollama", "local-openai-compatible"}:
        return True
    return bool(settings.embedding_api_key)


def get_embedding_identity() -> tuple[str, str]:
    return settings.embedding_provider, settings.embedding_model


def _normalize_embedding(raw_embedding: list[float] | tuple[float, ...]) -> list[float]:
    normalized = [float(value) for value in raw_embedding]
    if not normalized:
        raise ValueError("Embedding 回傳內容為空。")
    return normalized


def _normalize_embeddings(raw_embeddings: list[list[float]] | tuple[tuple[float, ...], ...]) -> list[list[float]]:
    return [_normalize_embedding(embedding) for embedding in raw_embeddings]


def _http_timeout() -> httpx.Timeout:
    return httpx.Timeout(300.0, connect=60.0)


async def _embed_texts_openai(texts: list[str]) -> list[list[float]]:
    headers = {"Content-Type": "application/json"}
    if settings.embedding_api_key:
        headers["Authorization"] = f"Bearer {settings.embedding_api_key}"

    payload: dict = {
        "model": settings.embedding_model,
        "input": texts,
    }
    if settings.embedding_dimensions > 0:
        payload["dimensions"] = settings.embedding_dimensions

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        response = await client.post(
            f"{settings.embedding_base_url}/embeddings",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        parsed = response.json()
        ordered = sorted(parsed["data"], key=lambda item: item["index"])
        return [_normalize_embedding(item["embedding"]) for item in ordered]


async def _embed_texts_ollama(texts: list[str]) -> list[list[float]]:
    base_url = _strip_openai_suffix(settings.embedding_base_url)
    payload = {
        "model": settings.embedding_model,
        "input": texts,
    }

    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        response = await client.post(f"{base_url}/api/embed", json=payload)

        if response.status_code == 404:
            legacy_embeddings: list[list[float]] = []
            for text in texts:
                legacy_payload = {
                    "model": settings.embedding_model,
                    "prompt": text,
                }
                legacy_response = await client.post(f"{base_url}/api/embeddings", json=legacy_payload)
                legacy_response.raise_for_status()
                legacy_parsed = legacy_response.json()

                single_embedding = legacy_parsed.get("embedding")
                if not isinstance(single_embedding, list):
                    raise ValueError(
                        f"Ollama 舊版 embeddings 回傳格式無法辨識: {json.dumps(legacy_parsed, ensure_ascii=False)}"
                    )

                legacy_embeddings.append(_normalize_embedding(single_embedding))

            return legacy_embeddings

        response.raise_for_status()
        parsed = response.json()

    embeddings = parsed.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return _normalize_embeddings(embeddings)

    single_embedding = parsed.get("embedding")
    if isinstance(single_embedding, list):
        return [_normalize_embedding(single_embedding)]

    raise ValueError("Ollama embeddings 回傳格式無法辨識。")


async def _embed_texts_gemini(texts: list[str]) -> list[list[float]]:
    results: list[list[float]] = []
    async with httpx.AsyncClient(timeout=_http_timeout()) as client:
        for text in texts:
            body: dict = {
                "content": {
                    "parts": [{"text": text}],
                }
            }
            if settings.embedding_dimensions > 0:
                body["outputDimensionality"] = settings.embedding_dimensions

            url = (
                f"{settings.embedding_base_url}/models/{settings.embedding_model}:embedContent"
                f"?key={settings.embedding_api_key}"
            )
            response = await client.post(url, json=body)
            response.raise_for_status()
            parsed = response.json()

            embedding = parsed.get("embedding", {}).get("values")
            if not isinstance(embedding, list):
                raise ValueError(
                    f"Gemini embeddings 回傳格式無法辨識: {json.dumps(parsed, ensure_ascii=False)}"
                )
            results.append(_normalize_embedding(embedding))

    return results


async def embed_text(text: str) -> list[float]:
    embeddings = await embed_texts([text])
    return embeddings[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    provider = settings.embedding_provider

    if provider in {"openai", "local-openai-compatible"}:
        return await _embed_texts_openai(texts)
    if provider == "ollama":
        return await _embed_texts_ollama(texts)
    if provider == "gemini":
        return await _embed_texts_gemini(texts)

    raise ValueError(f"不支援的 embedding provider: {provider}")
