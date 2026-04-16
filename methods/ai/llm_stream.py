from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import httpx

from methods.config.settings import settings


def build_system_prompt(enable_assistant_ui: bool = True) -> str:
    base_instruction = (
        "你是魚池監控 AI 助手。你會收到一份 context JSON，必須以 context 內容為主進行分析。\n"
        "規則如下：\n"
        "1. 先閱讀 session_summary_json、session_summary_text 與 conversation_history，接續既有對話。\n"
        "2. 若 context.time_window_trend.requested = true，優先根據該時間窗分析，不要忽略這段資料。\n"
        "3. 若 context.time_window_trend.mode = comparison，請分 current、previous、comparison 三段回答。\n"
        "4. 若 context.autonomous_time_window_trend.requested = true，代表系統已替你補查額外時間段，應納入分析。\n"
        "5. 回答趨勢時，優先使用 min_value、max_value、value_span、bucket_count，必要時說明白天晚上差異。\n"
        "6. 若 rag_retrieval.evidence_sufficient = false，需明確說明文獻證據不足。\n"
        "7. 不要自行在正文中編造 [1]、[2] 編號引用，也不要自己重排參考文獻；來源展示交給前端。\n"
        "8. 若資訊仍不足，應直接說明不足之處，不要捏造不存在的感測器資料。\n"
        "9. 若 time_window_suggestions 非空且目前沒有明確時間窗，應提醒使用者選時間。"
    )

    if enable_assistant_ui:
        return (
            base_instruction
            + "\n輸出格式：使用乾淨 Markdown，可使用標題、條列、表格，但避免過度裝飾。"
        )

    return base_instruction + "\n輸出格式：只輸出純文字，不要使用 Markdown 標題、表格、引用或程式碼區塊。"


def build_user_prompt(message: str, context: dict) -> str:
    return f"使用者問題：\n{message}\n\ncontext JSON：\n{json.dumps(context, ensure_ascii=False, indent=2)}"


def parse_retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text.strip() or response.reason_phrase

    if isinstance(payload, dict):
        error_obj = payload.get("error")
        if isinstance(error_obj, dict) and error_obj.get("message"):
            return str(error_obj["message"])
        if payload.get("message"):
            return str(payload["message"])

    return response.text.strip() or response.reason_phrase


def format_http_error(response: httpx.Response) -> str:
    detail = extract_error_message(response)
    if response.status_code == 429:
        return f"LLM API 已達到速率限制或配額限制。狀態碼: 429。詳細原因: {detail}"
    return f"LLM API 呼叫失敗。狀態碼: {response.status_code}。詳細原因: {detail}"


def extract_json_block(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    stripped = text.strip()
    candidates = [stripped]
    if "```json" in stripped:
        start = stripped.find("```json") + len("```json")
        end = stripped.rfind("```")
        if end > start:
            candidates.append(stripped[start:end].strip())
    elif "```" in stripped:
        start = stripped.find("```") + 3
        end = stripped.rfind("```")
        if end > start:
            candidates.append(stripped[start:end].strip())

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def normalize_web_source(provider: str, title: str | None, url: str | None) -> dict[str, Any] | None:
    normalized_title = (title or "").strip()
    normalized_url = (url or "").strip()
    if not normalized_url:
        return None
    return {
        "source_type": "web_search",
        "provider": provider,
        "title": normalized_title or normalized_url,
        "url": normalized_url,
        "label": f"[網路搜索] {normalized_title or normalized_url}",
    }


def deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique_sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for source in sources:
        url = str(source.get("url", "")).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_sources.append(source)
    return unique_sources


def extract_openai_response_text(payload: dict[str, Any]) -> str:
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


def extract_openai_web_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
                        normalized = normalize_web_source(
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
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                normalized = normalize_web_source(
                    provider="openai",
                    title=annotation.get("title"),
                    url=annotation.get("url"),
                )
                if normalized:
                    sources.append(normalized)
    return deduplicate_sources(sources)


def extract_gemini_text(payload: dict[str, Any]) -> str:
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


def extract_gemini_web_sources(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
        normalized = normalize_web_source(
            provider="gemini",
            title=web_info.get("title"),
            url=web_info.get("uri"),
        )
        if normalized:
            sources.append(normalized)
    return deduplicate_sources(sources)


async def yield_text_in_chunks(text: str, chunk_size: int = 18) -> AsyncGenerator[str, None]:
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


async def mock_token_stream(message: str, context: dict, enable_assistant_ui: bool = True) -> AsyncGenerator[str, None]:
    retrieval = context.get("rag_retrieval", {})
    time_window = context.get("time_window_trend") or {}
    history_count = context.get("conversation_history_count", 0)
    if enable_assistant_ui:
        reply = (
            "## 測試回覆\n"
            f"- 問題：{message}\n"
            f"- 魚池：{context.get('pond', {}).get('pond_name')}\n"
            f"- 歷史訊息數：{history_count}\n"
            f"- RAG 證據是否足夠：{retrieval.get('evidence_sufficient')}\n"
            f"- 是否有時間窗資料：{time_window.get('requested')}\n"
            "目前為 mock provider，請改用 OpenAI、Gemini 或 Ollama 取得正式回答。"
        )
    else:
        reply = (
            f"測試回覆：{message}\n"
            f"魚池：{context.get('pond', {}).get('pond_name')}\n"
            f"歷史訊息數：{history_count}\n"
            f"RAG 證據是否足夠：{retrieval.get('evidence_sufficient')}\n"
            f"是否有時間窗資料：{time_window.get('requested')}\n"
            "目前為 mock provider，請改用 OpenAI、Gemini 或 Ollama。"
        )

    async for chunk in yield_text_in_chunks(reply):
        yield chunk


async def complete_openai_compatible(
    *,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
) -> str:
    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode and settings.llm_provider == "openai":
        payload["response_format"] = {"type": "json_object"}

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    max_attempts = max(settings.llm_max_retries, 0) + 1
    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(
                f"{settings.llm_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )

            if response.is_success:
                parsed = response.json()
                try:
                    return str(parsed["choices"][0]["message"]["content"]).strip()
                except (KeyError, IndexError, TypeError) as err:
                    raise ValueError("LLM 未回傳可解析的文字內容。") from err

            if response.status_code == 429 and attempt < max_attempts:
                retry_after = parse_retry_after(response)
                wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                await asyncio.sleep(wait_seconds)
                continue

            raise ValueError(format_http_error(response))

    raise ValueError("LLM 呼叫失敗。")


async def complete_gemini(
    *,
    system_prompt: str,
    user_prompt: str,
) -> str:
    if not settings.llm_api_key:
        raise ValueError("Gemini 未設定 API Key。")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}],
            }
        ],
        "generationConfig": {
            "temperature": settings.llm_temperature,
        },
    }

    url = f"{settings.llm_base_url}/models/{settings.llm_model}:generateContent?key={settings.llm_api_key}"
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=body)
        if not response.is_success:
            raise ValueError(format_http_error(response))

        text = extract_gemini_text(response.json())
        if not text:
            raise ValueError("Gemini 未回傳可解析的文字內容。")
        return text


async def generate_text(
    *,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
) -> str:
    provider = settings.llm_provider
    if provider in {"openai", "ollama", "local-openai-compatible"}:
        return await complete_openai_compatible(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_mode=json_mode,
        )
    if provider == "gemini":
        return await complete_gemini(system_prompt=system_prompt, user_prompt=user_prompt)
    return json.dumps({"action": "none"}) if json_mode else "目前為 mock provider。"


async def generate_json(
    *,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any] | None:
    text = await generate_text(system_prompt=system_prompt, user_prompt=user_prompt, json_mode=True)
    return extract_json_block(text)


async def stream_openai_compatible(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "stream": True,
        "messages": [
            {"role": "system", "content": build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": build_user_prompt(message, context)},
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
                        except (KeyError, IndexError, json.JSONDecodeError, TypeError):
                            continue
                    return

                if response.status_code == 429 and attempt < max_attempts:
                    retry_after = parse_retry_after(response)
                    wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                    await response.aread()
                    await asyncio.sleep(wait_seconds)
                    continue

                await response.aread()
                raise ValueError(format_http_error(response))


async def stream_gemini(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    if not settings.llm_api_key:
        async for chunk in mock_token_stream(message, context, enable_assistant_ui):
            yield chunk
        return

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{build_system_prompt(enable_assistant_ui)}\n\n{build_user_prompt(message, context)}"}],
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
                raise ValueError(format_http_error(response))

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                content = line[5:].strip()
                if content == "[DONE]":
                    continue
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    continue
                candidates = parsed.get("candidates", [])
                if not isinstance(candidates, list) or not candidates:
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        yield str(part["text"])


async def generate_openai_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    if not settings.llm_api_key:
        raise ValueError("OpenAI 網路搜索需要設定 API Key。")

    payload = {
        "model": settings.llm_model,
        "input": [
            {"role": "system", "content": build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": build_user_prompt(message, context)},
        ],
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.llm_api_key}",
    }

    max_attempts = max(settings.llm_max_retries, 0) + 1
    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(f"{settings.llm_base_url}/responses", json=payload, headers=headers)
            if response.is_success:
                parsed = response.json()
                output_text = extract_openai_response_text(parsed)
                if not output_text:
                    raise ValueError("OpenAI 網路搜索未回傳可用文字內容。")
                return output_text, extract_openai_web_sources(parsed)

            if response.status_code == 429 and attempt < max_attempts:
                retry_after = parse_retry_after(response)
                wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                await asyncio.sleep(wait_seconds)
                continue

            raise ValueError(format_http_error(response))

    raise ValueError("OpenAI 網路搜索失敗。")


async def generate_gemini_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    if not settings.llm_api_key:
        raise ValueError("Gemini 網路搜索需要設定 API Key。")

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{build_system_prompt(enable_assistant_ui)}\n\n{build_user_prompt(message, context)}"}],
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": settings.llm_temperature,
        },
    }
    url = f"{settings.llm_base_url}/models/{settings.llm_model}:generateContent?key={settings.llm_api_key}"
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=body)
        if not response.is_success:
            raise ValueError(format_http_error(response))
        parsed = response.json()
        output_text = extract_gemini_text(parsed)
        if not output_text:
            raise ValueError("Gemini 網路搜索未回傳可用文字內容。")
        return output_text, extract_gemini_web_sources(parsed)


async def generate_web_search_response(
    message: str,
    context: dict,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    if settings.llm_provider == "openai":
        return await generate_openai_web_search_response(message, context, enable_assistant_ui)
    if settings.llm_provider == "gemini":
        return await generate_gemini_web_search_response(message, context, enable_assistant_ui)
    raise ValueError("只有 OpenAI 或 Gemini provider 可啟用網路搜索。")


async def stream_chat_tokens(
    message: str,
    context: dict,
    enable_web_search: bool = False,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    provider = settings.llm_provider
    if enable_web_search and provider not in {"openai", "gemini"}:
        raise ValueError("只有 OpenAI 或 Gemini provider 可啟用網路搜索。")

    if provider in {"openai", "ollama", "local-openai-compatible"}:
        if enable_web_search and provider == "openai":
            output_text, _ = await generate_openai_web_search_response(message, context, enable_assistant_ui)
            async for chunk in yield_text_in_chunks(output_text):
                yield chunk
            return

        async for token in stream_openai_compatible(message, context, enable_assistant_ui):
            yield token
        return

    if provider == "gemini":
        if enable_web_search:
            output_text, _ = await generate_gemini_web_search_response(message, context, enable_assistant_ui)
            async for chunk in yield_text_in_chunks(output_text):
                yield chunk
            return

        async for token in stream_gemini(message, context, enable_assistant_ui):
            yield token
        return

    async for chunk in mock_token_stream(message, context, enable_assistant_ui):
        yield chunk
