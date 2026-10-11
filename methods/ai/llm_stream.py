from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import httpx

from methods.config.settings import settings
from methods.config.model_config import get_model_capability
from methods.base.schemas import Attachment


def build_system_prompt(enable_assistant_ui: bool = True) -> str:
    base_instruction = (
        "你是魚池監控 AI 助手。你會收到一份 context JSON，必須以 context 內容為主進行分析。\n"
        "規則如下：\n"
        "1. 先閱讀 session_summary_json、session_summary_text 與 conversation_history，接續既有對話。\n"
        "2. 若 context.time_window_trend.requested = true，優先根據該時間窗分析，不要忽略這段資料。\n"
        "3. 若 context.time_window_trend.mode = comparison，請分 current、previous、comparison 三段回答。\n"
        "4. 若 context.autonomous_time_window_trend.requested = true，代表系統已替你補查額外時間段，應納入分析。\n"
        "5. 回答趨勢時，優先使用 min_value、max_value、value_span、bucket_count，必要時說明白天晚上差異。\n"
        "6. 必須分析 context.daily_logs 中的關鍵行為：\n"
        "   - 基本數據：feeding_amount (投餵量)、death_count (死亡數)。\n"
        "   - 詳細投入品 (items 陣列)：遍歷 items 並根據 category 進行分類分析：\n"
        "     * feed_additive (飼料添加物)：分析對生長與抗病力的影響。\n"
        "     * pond_medication (用藥)：分析治療行為與魚隻死亡/健康狀況的因果。\n"
        "     * maintenance_material (水質改良劑/資材)：分析與感測器數值變化的關聯。\n"
        "7. 若 rag_retrieval.evidence_sufficient = false，需明確說明文獻證據不足。\n"
        "8. 不要自行在正文中編造 [1]、[2] 編號引用，也不要自己重排參考文獻；來源展示交給前端。\n"
        "9. 若資訊仍不足，應直接說明不足之處，不要捏造不存在的感測器資料。\n"
        "10. 若 time_window_suggestions 非空且目前沒有明確時間窗，應提醒使用者選時間。\n"
        "11. 你的首要任務是「解決使用者提出的問題」。提供的 context (感測器、日誌、RAG) 僅為分析輔助：若與問題高度相關則積極使用，若資料與問題無關，則不應受其干擾或強行引用。"
    )

    if enable_assistant_ui:
        return (
            base_instruction
            + "\n輸出格式：使用乾淨 Markdown，可使用標題、條列、表格，但避免過度裝飾。"
        )

    return base_instruction + "\n輸出格式：只輸出純文字，不要使用 Markdown 標題、表格、引用或程式碼區塊。"


def build_openai_user_parts(message: str, context: dict, attachments: list[Attachment] | None = None) -> list[dict[str, Any]]:
    text_content = f"使用者問題：\n{message}\n\ncontext JSON：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    parts = [{"type": "text", "text": text_content}]
    
    if attachments:
        for att in attachments:
            if att.type == "image":
                img_part = {"type": "image_url"}
                if att.url:
                    img_part["image_url"] = {"url": att.url}
                elif att.data:
                    mime = att.mime_type or "image/jpeg"
                    img_part["image_url"] = {"url": f"data:{mime};base64,{att.data}"}
                parts.append(img_part)
            elif att.type == "file":
                if att.url and att.url.startswith("file-"):
                    parts.append({
                        "type": "file",
                        "file": {"file_id": att.url}
                    })
                elif att.data:
                    # Chat Completions 的檔案輸入使用 PDF 的 data URL。
                    mime = att.mime_type or "application/pdf"
                    if mime != "application/pdf":
                        raise ValueError("此模型的檔案輸入目前只支援 PDF，請改用 PDF 附件。")
                    parts.append({
                        "type": "file",
                        "file": {
                            "filename": att.name or "attachment.pdf",
                            "file_data": f"data:{mime};base64,{att.data}",
                        },
                    })
                else:
                    raise ValueError("檔案附件缺少內容或有效的檔案 ID。")
    return parts


def build_gemini_contents(system_prompt: str, message: str, context: dict, attachments: list[Attachment] | None = None) -> list[dict[str, Any]]:
    text_content = f"{system_prompt}\n\n使用者問題：\n{message}\n\ncontext JSON：\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    parts = [{"text": text_content}]
    
    if attachments:
        for att in attachments:
            if att.data:
                parts.append({
                    "inline_data": {
                        "mime_type": att.mime_type or ("image/jpeg" if att.type == "image" else "application/pdf"),
                        "data": att.data
                    }
                })
    return [{"role": "user", "parts": parts}]


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


def extract_openai_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", [])
    if choices:
        return str(choices[0].get("message", {}).get("content", "")).strip()

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    text_segments: list[str] = []
    output_items = payload.get("output", [])
    if isinstance(output_items, list):
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

    text_segments = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        # 捕捉文字內容
        if part.get("text"):
            text_segments.append(str(part["text"]))
        # 捕捉思考內容 (Gemini 2.0/3.x 規格)
        elif part.get("thought"):
            text_segments.append(f"\n> [Thinking]: {part['thought']}\n")
    
    return "".join(text_segments).strip()


async def yield_text_in_chunks(text: str, chunk_size: int = 18) -> AsyncGenerator[str, None]:
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


async def mock_token_stream(message: str, context: dict, enable_assistant_ui: bool = True) -> AsyncGenerator[str, None]:
    reply = f"這是來自 Mock Provider 的測試。問題：{message}"
    async for chunk in yield_text_in_chunks(reply):
        yield chunk


def get_provider_config(provider: str) -> tuple[str, str]:
    """根據 provider 回傳對應的 (api_key, base_url)"""
    def clean_key(key: str | None) -> str:
        if not key:
            return ""
        s = key.strip()
        while s.startswith(('"', "'", "=")) or s.endswith(('"', "'")):
            s = s.strip().strip('"').strip("'").lstrip("=")
        return s

    if provider == "openai":
        return clean_key(settings.openai_api_key), settings.openai_base_url
    if provider == "gemini":
        return clean_key(settings.gemini_api_key), settings.gemini_base_url
    if provider in {"ollama", "local-openai-compatible"}:
        return clean_key(settings.ollama_api_key), settings.ollama_base_url
    
    return clean_key(settings.llm_api_key), settings.llm_base_url


async def stream_openai_compatible(
    message: str,
    context: dict,
    model_override: str | None = None,
    attachments: list[Attachment] | None = None,
    deep_thinking: bool = False,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    model = model_override or settings.llm_default_model
    capability = get_model_capability(model)
    provider = capability.get("provider", "openai")
    api_key, base_url = get_provider_config(provider)
    
    deep_thinking_level = capability.get("deep_thinking_level", "high")
    
    user_parts = build_openai_user_parts(
        message, 
        context, 
        attachments if capability.get("supports_multimodal") else None
    )

    payload = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": user_parts},
        ],
    }
    
    # Chat Completions 使用 reasoning_effort，與 Responses 的欄位不同。
    if deep_thinking and capability.get("enabled") and capability.get("supports_deep_thinking") and capability.get("thinking_type") == "openai_effort":
        payload["reasoning_effort"] = deep_thinking_level
        
    if not capability.get("disallow_temperature", False):
        payload["temperature"] = settings.llm_temperature
    elif "temperature" in payload:
        del payload["temperature"]

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    max_attempts = max(settings.llm_max_retries, 0) + 1
    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
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
                            choices = parsed.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            
                            # 捕捉思考內容
                            reasoning = delta.get("reasoning_content")
                            if reasoning:
                                yield reasoning
                                
                            token = delta.get("content")
                            if token:
                                yield token
                        except (KeyError, IndexError, json.JSONDecodeError, TypeError):
                            continue
                    return

                if response.status_code == 429 and attempt < max_attempts:
                    retry_after = parse_retry_after(response)
                    wait_seconds = retry_after if retry_after is not None else settings.llm_retry_base_seconds * attempt
                    await asyncio.sleep(wait_seconds)
                    continue

                await response.aread()
                raise ValueError(format_http_error(response))


async def stream_gemini(
    message: str,
    context: dict,
    model_override: str | None = None,
    attachments: list[Attachment] | None = None,
    deep_thinking: bool = False,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    model = model_override or settings.llm_default_model
    capability = get_model_capability(model)
    api_key, base_url = get_provider_config("gemini")

    if not api_key:
        async for chunk in mock_token_stream(message, context, enable_assistant_ui):
            yield chunk
        return

    deep_thinking_level = capability.get("deep_thinking_level", "high")
    
    generation_config: dict[str, Any] = {}
    if not capability.get("disallow_temperature", False):
        generation_config["temperature"] = settings.llm_temperature

    if deep_thinking and capability.get("enabled") and capability.get("supports_deep_thinking"):
        if capability["thinking_type"] == "gemini_budget":
            # 根據您提供的規格：2.5 系列使用 thinkingBudget
            budget_map = {"high": 24576, "medium": 8192, "low": 4096}
            budget = budget_map.get(deep_thinking_level, 16384)
            generation_config["thinkingConfig"] = {"thinkingBudget": budget}
        elif capability["thinking_type"] == "gemini_level":
            # 根據您提供的規格：3.x 系列使用 thinkingLevel
            level = deep_thinking_level if deep_thinking_level in ["minimal", "low", "medium", "high"] else "medium"
            generation_config["thinkingConfig"] = {"thinkingLevel": level}

    contents = build_gemini_contents(
        build_system_prompt(enable_assistant_ui), 
        message, 
        context, 
        attachments if capability.get("supports_multimodal") else None
    )

    body = {
        "contents": contents,
        "generationConfig": generation_config,
    }

    url = (
        f"{base_url}/models/{model}:streamGenerateContent"
        f"?alt=sse&key={api_key}"
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
                    if not isinstance(part, dict):
                        continue
                    # 捕捉思考過程，避免長時間空白中斷
                    if part.get("thought"):
                        yield str(part["thought"])
                    if part.get("text"):
                        yield str(part["text"])


async def generate_text(
    *,
    system_prompt: str,
    user_prompt: str,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    target_model = model or settings.llm_default_model
    capability = get_model_capability(target_model)
    provider = capability.get("provider", "unknown")
    if provider == "unknown":
        provider = settings.llm_provider
    
    api_key, base_url = get_provider_config(provider)

    if provider == "gemini":
        url = f"{base_url}/models/{target_model}:generateContent?key={api_key}"
        gen_config = {}
        if not capability.get("disallow_temperature", False):
            gen_config["temperature"] = settings.llm_temperature
            
        body = {
            "contents": [{"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}],
            "generationConfig": gen_config
        }
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(url, json=body)
            if not response.is_success:
                raise ValueError(format_http_error(response))
            return extract_gemini_text(response.json())
    
    payload = {
        "model": target_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if not capability.get("disallow_temperature", False):
        payload["temperature"] = settings.llm_temperature

    if json_mode and provider == "openai":
        payload["response_format"] = {"type": "json_object"}
    
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        if not response.is_success:
            raise ValueError(format_http_error(response))
        return extract_openai_response_text(response.json())


async def generate_json(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
) -> dict[str, Any] | None:
    text = await generate_text(system_prompt=system_prompt, user_prompt=user_prompt, json_mode=True, model=model)
    return extract_json_block(text)


async def stream_chat_tokens(
    message: str,
    context: dict,
    model: str | None = None,
    attachments: list[Attachment] | None = None,
    deep_thinking: bool = False,
    enable_web_search: bool = False,
    enable_assistant_ui: bool = True,
) -> AsyncGenerator[str, None]:
    target_model = model or settings.llm_default_model
    capability = get_model_capability(target_model)
    
    provider = capability.get("provider")
    if not provider or provider == "unknown":
        provider = settings.llm_provider

    if provider in {"openai", "ollama", "local-openai-compatible"}:
        async for token in stream_openai_compatible(
            message, context, target_model, attachments, deep_thinking, enable_assistant_ui
        ):
            yield token
    elif provider == "gemini":
        async for token in stream_gemini(
            message, context, target_model, attachments, deep_thinking, enable_assistant_ui
        ):
            yield token
    else:
        async for chunk in mock_token_stream(message, context, enable_assistant_ui):
            yield chunk


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


async def generate_openai_web_search_response(
    message: str,
    context: dict,
    model: str | None = None,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    api_key, base_url = get_provider_config("openai")
    if not api_key:
        raise ValueError("OpenAI 網路搜索需要設定 OPENAI_API_KEY。")

    target_model = model or settings.llm_default_model
    capability = get_model_capability(target_model)

    # 修改：根據您提供的規格使用 "reasoning": {"effort": ...}
    payload = {
        "model": target_model,
        "input": [
            {"role": "system", "content": build_system_prompt(enable_assistant_ui)},
            {"role": "user", "content": f"使用者問題：\n{message}\n\ncontext JSON：\n{json.dumps(context, ensure_ascii=False, indent=2)}"},
        ],
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
    }
    
    if capability.get("supports_deep_thinking"):
        payload["reasoning"] = {"effort": capability.get("deep_thinking_level", "high")}

    if not capability.get("disallow_temperature", False):
        payload["temperature"] = settings.llm_temperature

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    max_attempts = max(settings.llm_max_retries, 0) + 1
    async with httpx.AsyncClient(timeout=None) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(f"{base_url}/responses", json=payload, headers=headers)
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
    model: str | None = None,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    api_key, base_url = get_provider_config("gemini")
    if not api_key:
        raise ValueError("Gemini 網路搜索需要設定 GEMINI_API_KEY。")

    target_model = model or settings.llm_default_model
    capability = get_model_capability(target_model)

    gen_config = {}
    if not capability.get("disallow_temperature", False):
        gen_config["temperature"] = settings.llm_temperature

    if capability.get("supports_deep_thinking"):
        level = capability.get("deep_thinking_level", "high")
        if capability.get("thinking_type") == "gemini_budget":
            budget_map = {"high": 24576, "medium": 8192, "low": 4096}
            gen_config["thinkingConfig"] = {"thinkingBudget": budget_map.get(level, 16384)}
        else:
            gen_config["thinkingConfig"] = {"thinkingLevel": level}

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{build_system_prompt(enable_assistant_ui)}\n\n使用者問題：\n{message}\n\ncontext JSON：\n{json.dumps(context, ensure_ascii=False, indent=2)}"}],
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": gen_config,
    }
    url = f"{base_url}/models/{target_model}:generateContent?key={api_key}"
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
    model: str | None = None,
    enable_assistant_ui: bool = True,
) -> tuple[str, list[dict[str, Any]]]:
    target_model = model or settings.llm_default_model
    capability = get_model_capability(target_model)
    provider = capability.get("provider", "unknown")
    if provider == "unknown":
        provider = settings.llm_provider

    if provider == "openai":
        return await generate_openai_web_search_response(message, context, target_model, enable_assistant_ui)
    if provider == "gemini":
        return await generate_gemini_web_search_response(message, context, target_model, enable_assistant_ui)
    raise ValueError(f"Provider '{provider}' 不支援網路搜索。")
