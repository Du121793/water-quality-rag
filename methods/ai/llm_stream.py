from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import httpx

from methods.config.settings import settings


def _build_system_prompt(enable_assistant_ui: bool = True) -> str:
    base_instruction = """
你是魚塭 AI 助理。你會收到一份完整的 context JSON，請嚴格依據其中資料回答。

你必須遵守：
1. 優先閱讀 `session_summary_json` 與 `session_summary_text`，把它們視為跨回合長期記憶。
2. 優先閱讀 `conversation_history`，把它視為同一個 session 的最近對話。
3. 如果 `time_window_trend.requested = true`，就直接使用該時間窗，不要自行改寫時間範圍。
4. 如果 `time_window_trend.mode = comparison`，請明確比較 current / previous / comparison。
5. 請優先使用 `trend.summary` 中的 `min_value / max_value / value_span / bucket_count` 來判斷波動。
6. 24 小時的趨勢同時有 `hourly` 與 `ten_minute`，請依問題需求比較白天與夜晚或短期變化。
7. 若 `rag_retrieval.evidence_sufficient = false`，請明確承認證據不足，不要硬下結論。
8. 不要自行發明 `[1] [2]` 的引用編號。引用只使用 `citations` 與 `web_search_sources`。
9. 若 `enable_assistant_ui = true`，可使用 Markdown、表格、清單、引用區塊。
   若為 false，請只輸出純文字，不要輸出 Markdown 標題、表格、清單、程式碼區塊或引用區塊。
10. 當使用者問法明確指向特定時間範圍時，請沿用 context 中已解析的時間窗。
    當問題不夠明確時，請善用 `time_window_suggestions` 提醒使用者選時間。
"""

    if enable_assistant_ui:
        return base_instruction + """
輸出格式：
- 使用乾淨的 Markdown。
- 回答要有結構，但不要過度冗長。
- 論文引用與網路搜尋來源分開呈現。
"""

    return base_instruction + """
輸出格式：
- 只輸出純文字。
- 不要使用 Markdown 標題、表格、清單、引用區塊或程式碼區塊。
"""


def _build_user_prompt(message: str, context: dict) -> str:
    return (
        f"使用者問題：\n{message}\n\n"
        f"可用 context：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None

    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text.strip() or response.reason_phrase

    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict):
            message = error_obj.get("message")
            if message:
                return str(message)
        message = payload.get("message")
        if message:
            return str(message)

    return response.text.strip() or response.reason_phrase


def _format_http_error(response: httpx.Response) -> str:
    detail = _extract_error_message(response)
    if response.status_code == 429:
        return f"LLM API 已達到速率限制或帳戶配額限制。狀態碼: 429。詳細原因: {detail}"
    return f"LLM API 請求失敗。狀態碼: {response.status_code}。詳細原因: {detail}"


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_segments: list[str] = []
    output_items = payload.get("output", [])
    if not isinstance(output_items, list):
        return ""

    for item in output_items:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue

        content_items = item.get("content", [])
        if not isinstance(content_items, list):
            continue

        for content in content_items:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text:
                    text_segments.append(text)

    return "".join(text_segments).strip()


def _normalize_web_source(provider: str, title: str | None, url: str | None) -> dict[str, Any] | None:
    normalized_title = (title or "").strip()
    normalized_url = (url or "").strip()
    if not normalized_url:
        return None

    return {
        "source_type": "web_search",
        "provider": provider,
        "title": normalized_title or normalized_url,
        "url": normalized_url,
        "label": f"[網路搜尋] {normalized_title or normalized_url}",
    }


def _deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for source in sources:
        url = str(source.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_sources.append(source)

    return unique_sources


def _extract_openai_web_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    output_items = payload.get("output", [])
    if not isinstance(output_items, list):
        return sources

    for item in output_items:
        if not isinstance(item, dict):
            continue

        if item.get("type") == "web_search_call":
            action = item.get("action", {})
            if isinstance(action, dict):
                action_sources = action.get("sources", [])
                if isinstance(action_sources, list):
                    for source in action_sources:
                        if not isinstance(source, dict):
                            continue
                        normalized = _normalize_web_source(
                            provider="openai",
                            title=source.get("title"),
                            url=source.get("url"),
                        )
                        if normalized:
                            sources.append(normalized)

        if item.get("type") != "message":
            continue

        content_items = item.get("content", [])
        if not isinstance(content_items, list):
            continue

        for content in content_items:
            if not isinstance(content, dict) or content.get("type") != "output_text":
                continue

            annotations = content.get("annotations", [])
            if not isinstance(annotations, list):
                continue

            for annotation in annotations:
                if not isinstance(annotation, dict):
                    continue
                if annotation.get("type") != "url_citation":
                    continue

                normalized = _normalize_web_source(
                    provider="openai",
                    title=annotation.get("title"),
                    url=annotation.get("url"),
                )
                if normalized:
                    sources.append(normalized)

    return _deduplicate_sources(sources)


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return ""

    content = candidates[0].get("content", {})
    if not isinstance(content, dict):
        return ""

    parts = content.get("parts", [])
    if not isinstance(parts, list):
        return ""

    text_segments = [part.get("text", "") for part in parts if isinstance(part, dict) and part.get("text")]
    return "".join(text_segments).strip()


def _extract_gemini_web_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return []

    grounding_metadata = candidates[0].get("groundingMetadata", {})
    if not isinstance(grounding_metadata, dict):
        return []

    grounding_chunks = grounding_metadata.get("groundingChunks", [])
    if not isinstance(grounding_chunks, list):
        return []

    sources: list[dict[str, Any]] = []
    for chunk in grounding_chunks:
        if not isinstance(chunk, dict):
            continue

        web_info = chunk.get("web", {})
        if not isinstance(web_info, dict):
            continue

        normalized = _normalize_web_source(
            provider="gemini",
            title=web_info.get("title"),
            url=web_info.get("uri"),
        )
        if normalized:
            sources.append(normalized)

    return _deduplicate_sources(sources)


async def yield_text_in_chunks(text: str, chunk_size: int = 18) -> AsyncGenerator[str, None]:
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


async def _mock_token_stream(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    retrieval = context.get("rag_retrieval", {})
    time_window = context.get("time_window_trend") or {}
    history_count = context.get("conversation_history_count", 0)

    if enable_assistant_ui:
        reply = (
            "## 模擬回覆\n"
            f"- 使用者問題：{message}\n"
            f"- 魚池：{context.get('pond', {}).get('pond_name')}\n"
            f"- 最近對話筆數：{history_count}\n"
            f"- RAG 證據充分：{retrieval.get('evidence_sufficient')}\n"
            f"- 是否需要時間窗：{time_window.get('requested')}\n\n"
            "這是 mock provider 的回應，正式環境請切換到 OpenAI / Gemini / Ollama。"
        )
    else:
        reply = (
            f"模擬回覆：{message}\n"
            f"魚池：{context.get('pond', {}).get('pond_name')}\n"
            f"最近對話筆數：{history_count}\n"
            f"RAG 證據充分：{retrieval.get('evidence_sufficient')}\n"
            f"是否需要時間窗：{time_window.get('requested')}\n"
            "這是 mock provider 的回應，正式環境請切換到 OpenAI / Gemini / Ollama。"
        )

    async for chunk in yield_text_in_chunks(reply):
        yield chunk


async def _stream_openai_chat_completions(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "stream": True,
        "messages": [
            {"role": "system", "content": _build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": _build_user_prompt(message, context)},
        ],
    }

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    max_attempts = max(settings.llm_max_retries, 0) + 1

    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            async with client.stream(
                "POST",
                f"{settings.llm_base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.is_success:
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue

                        content = line[5:].strip()
                        if content == "[DONE]":
                            continue

                        try:
                            parsed = json.loads(content)
                            token = parsed["choices"][0]["delta"].get("content")
                            if token:
                                yield token
                        except (KeyError, IndexError, json.JSONDecodeError):
                            continue
                    return

                if response.status_code == 429 and attempt < max_attempts:
                    retry_after = _parse_retry_after(response)
                    wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                    await response.aread()
                    await asyncio.sleep(wait_seconds)
                    continue

                await response.aread()
                raise ValueError(_format_http_error(response))


async def generate_openai_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    if not settings.llm_api_key:
        raise ValueError("OpenAI 網路搜索需要 API Key。")

    payload = {
        "model": settings.llm_model,
        "input": [
            {"role": "system", "content": _build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": _build_user_prompt(message, context)},
        ],
        "tools": [
            {"type": "web_search"},
        ],
        "include": ["web_search_call.action.sources"],
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm_api_key}",
    }

    max_attempts = max(settings.llm_max_retries, 0) + 1
    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(
                f"{settings.llm_base_url}/responses",
                json=payload,
                headers=headers,
            )

            if response.is_success:
                parsed = response.json()
                output_text = _extract_openai_response_text(parsed)
                if not output_text:
                    raise ValueError("OpenAI 網路搜索未回傳可用文字內容。")
                return output_text, _extract_openai_web_sources(parsed)

            if response.status_code == 429 and attempt < max_attempts:
                retry_after = _parse_retry_after(response)
                wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                await asyncio.sleep(wait_seconds)
                continue

            raise ValueError(_format_http_error(response))

    raise ValueError("OpenAI 網路搜索失敗。")


async def _stream_gemini_stream(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    if not settings.llm_api_key:
        async for chunk in _mock_token_stream(message, context, enable_assistant_ui):
            yield chunk
        return

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{_build_system_prompt(enable_assistant_ui)}\n\n"
                            f"{_build_user_prompt(message, context)}"
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": settings.llm_temperature,
        },
    }

    url = (
        f"{settings.llm_base_url}/models/{settings.llm_model}:streamGenerateContent"
        f"?alt=sse&key={settings.llm_api_key}"
    )

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=body) as response:
            if not response.is_success:
                await response.aread()
                raise ValueError(_format_http_error(response))

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue

                content = line[5:].strip()
                if content == "[DONE]":
                    continue

                try:
                    parsed = json.loads(content)
                    candidates = parsed.get("candidates", [])
                    if not candidates:
                        continue

                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        text = part.get("text")
                        if text:
                            yield text
                except json.JSONDecodeError:
                    continue


async def generate_gemini_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    if not settings.llm_api_key:
        raise ValueError("Gemini 網路搜索需要 API Key。")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            f"{_build_system_prompt(enable_assistant_ui)}\n\n"
                            f"{_build_user_prompt(message, context)}"
                        )
                    }
                ],
            }
        ],
        "tools": [
            {"google_search": {}},
        ],
        "generationConfig": {
            "temperature": settings.llm_temperature,
        },
    }

    url = f"{settings.llm_base_url}/models/{settings.llm_model}:generateContent?key={settings.llm_api_key}"

    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=body)
        if not response.is_success:
            raise ValueError(_format_http_error(response))

        parsed = response.json()
        output_text = _extract_gemini_text(parsed)
        if not output_text:
            raise ValueError("Gemini 網路搜索未回傳可用文字內容。")

        return output_text, _extract_gemini_web_sources(parsed)


async def generate_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    provider = settings.llm_provider

    if provider == "openai":
        return await generate_openai_web_search_response(message, context, enable_assistant_ui)

    if provider == "gemini":
        return await generate_gemini_web_search_response(message, context, enable_assistant_ui)

    raise ValueError("只有 OpenAI 或 Gemini provider 才能啟用 enable_web_search。")


async def stream_chat_tokens(
    message: str,
    context: dict,
    enable_web_search: bool = False,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    provider = settings.llm_provider

    if enable_web_search and provider not in {"openai", "gemini"}:
        raise ValueError("只有 OpenAI 或 Gemini provider 才能啟用 enable_web_search。")

    if provider in {"openai", "ollama", "local-openai-compatible"}:
        if enable_web_search and provider == "openai":
            output_text, _ = await generate_openai_web_search_response(message, context, enable_assistant_ui)
            async for chunk in yield_text_in_chunks(output_text):
                yield chunk
            return

        async for token in _stream_openai_chat_completions(message, context, enable_assistant_ui):
            yield token
        return

    if provider == "gemini":
        if enable_web_search:
            output_text, _ = await generate_gemini_web_search_response(message, context, enable_assistant_ui)
            async for chunk in yield_text_in_chunks(output_text):
                yield chunk
            return

        async for token in _stream_gemini_stream(message, context, enable_assistant_ui):
            yield token
        return

    async for chunk in _mock_token_stream(message, context, enable_assistant_ui):
        yield chunk
