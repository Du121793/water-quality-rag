from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from SQL_Controller.ai_audit_logs import (
    complete_ai_audit_log,
    create_ai_audit_log,
    fail_ai_audit_log,
)
from SQL_Controller.chat_sessions import (
    delete_chat_session,
    ensure_chat_session,
    get_chat_session,
    insert_chat_message,
    list_chat_messages,
    list_chat_sessions_by_user,
    list_recent_chat_messages,
    update_chat_session_summary,
)
from methods.ai.auth import resolve_web_user_id
from methods.ai.chat_context import build_pond_context
from methods.ai.conversation_memory import (
    build_session_summary_state,
    normalize_session_summary_state,
    render_session_summary_text,
    trim_chat_history_by_budget,
)
from methods.ai.llm_stream import (
    generate_web_search_response,
    stream_chat_tokens,
    yield_text_in_chunks,
)
from methods.base.logger import error, info, warn
from methods.base.schemas import ChatStreamRequest
from methods.base.sse import format_sse
from methods.config.settings import settings

router = APIRouter()


def _has_meaningful_session_summary(summary_state: dict) -> bool:
    return bool(
        summary_state.get("current_goal")
        or summary_state.get("confirmed_facts")
        or summary_state.get("open_questions")
        or summary_state.get("recent_topics")
        or summary_state.get("legacy_summary_text")
    )


def _build_time_window_summary(context: dict) -> dict:
    time_window = context.get("time_window_trend") or {}
    if not time_window or not time_window.get("requested"):
        return {
            "requested": False,
            "selection_required": bool(context.get("time_window_suggestions")),
        }

    summary = {
        "requested": True,
        "mode": time_window.get("mode", "single"),
        "matched_by": time_window.get("matched_by"),
        "from_at": time_window.get("from_at"),
        "to_at": time_window.get("to_at"),
        "metrics": time_window.get("metrics", []),
        "bucket": time_window.get("bucket"),
        "requested_bucket": time_window.get("requested_bucket"),
        "was_capped": time_window.get("was_capped", False),
        "original_days": time_window.get("original_days"),
        "adjusted_days": time_window.get("adjusted_days"),
    }

    if summary["mode"] == "comparison":
        summary["comparison_matched_by"] = time_window.get("comparison_matched_by")
        summary["previous_from_at"] = time_window.get("previous_from_at")
        summary["previous_to_at"] = time_window.get("previous_to_at")

    return summary


@router.get("/sessions")
async def list_sessions(
    request: Request,
    user_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    resolved_user_id = await resolve_web_user_id(request, user_id)
    sessions = await list_chat_sessions_by_user(resolved_user_id, limit=limit)
    return {
        "success": True,
        "data": sessions,
    }


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    request: Request,
    user_id: int | None = Query(default=None),
):
    resolved_user_id = await resolve_web_user_id(request, user_id)
    session = await get_chat_session(session_id)

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    if int(session["user_id"]) != resolved_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this session.")

    return {
        "success": True,
        "data": {
            "session": session,
            "messages": await list_chat_messages(session_id),
        },
    }


@router.delete("/sessions/{session_id}")
async def remove_session(
    session_id: str,
    request: Request,
    user_id: int | None = Query(default=None),
):
    resolved_user_id = await resolve_web_user_id(request, user_id)
    session = await get_chat_session(session_id)

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")

    if int(session["user_id"]) != resolved_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this session.")

    await delete_chat_session(session_id)
    return {
        "success": True,
        "message": "Session deleted.",
    }


@router.post("/chat/stream")
async def chat_stream(request: Request, payload: ChatStreamRequest):
    user_id = await resolve_web_user_id(request, payload.user_id)
    request_id = str(uuid.uuid4())
    session_id = payload.session_id or str(uuid.uuid4())
    session_title = payload.message[:80]

    async def event_generator():
        audit_log_id = None
        final_content: list[str] = []
        web_search_sources: list[dict] = []
        conversation_history: list[dict] = []
        conversation_history_stats: dict = {}
        session_summary_state: dict = {}
        session_summary_text = ""

        try:
            info("AI對話", f"開始處理 request_id={request_id}", request.client.host if request.client else "")

            session = await ensure_chat_session(
                session_id=session_id,
                user_id=user_id,
                pond_id=payload.pond_id,
                title=session_title,
            )

            try:
                session_summary_state = normalize_session_summary_state(
                    session.get("summary_json"),
                    legacy_summary_text=str(session.get("summary") or ""),
                )
                session_summary_text = render_session_summary_text(
                    session_summary_state,
                    settings.chat_session_summary_max_chars,
                )
            except Exception as summary_err:
                warn("AI對話", f"載入 session 摘要失敗，改用空摘要：{summary_err}")
                session_summary_state = normalize_session_summary_state({})
                session_summary_text = ""

            try:
                recent_messages = await list_recent_chat_messages(
                    session_id=session_id,
                    limit=settings.chat_history_message_limit,
                )
                conversation_history, conversation_history_stats = trim_chat_history_by_budget(
                    recent_messages,
                    settings.chat_history_max_chars,
                )
            except Exception as history_err:
                warn("AI對話", f"載入歷史對話失敗，改用空歷史：{history_err}")
                conversation_history = []
                conversation_history_stats = {}

            await insert_chat_message(
                session_id=session_id,
                role="user",
                message=payload.message,
                metadata={
                    "request_id": request_id,
                    "time_window_from": payload.time_window_from,
                    "time_window_to": payload.time_window_to,
                    "compare_previous_window": payload.compare_previous_window,
                },
            )

            context = await build_pond_context(
                user_id,
                payload.pond_id,
                payload.message,
                use_rag=payload.use_rag,
                time_window_from=payload.time_window_from,
                time_window_to=payload.time_window_to,
                compare_previous_window=payload.compare_previous_window,
                session_summary_state=session_summary_state,
            )
            context["use_rag"] = payload.use_rag
            context["enable_web_search"] = payload.enable_web_search
            context["enable_assistant_ui"] = payload.enable_assistant_ui
            context["session_summary_json"] = session_summary_state
            context["session_summary_text"] = session_summary_text
            context["session_summary"] = session_summary_text
            context["conversation_history"] = conversation_history
            context["conversation_history_count"] = len(conversation_history)
            context["conversation_history_stats"] = conversation_history_stats

            time_window_summary = _build_time_window_summary(context)

            audit_log_id = await create_ai_audit_log(
                request_id=request_id,
                user_id=user_id,
                pond_id=payload.pond_id,
                question=payload.message,
                context_summary=context,
            )

            yield format_sse("start", {"request_id": request_id, "session_id": session_id})

            source_payload = {
                "pond_name": context["pond"]["pond_name"],
                "paper_count": len(context["rag_references"]),
                "citations": context.get("citations", []),
                "rag_retrieval": context.get("rag_retrieval", {}),
                "use_rag": payload.use_rag,
                "enable_web_search": payload.enable_web_search,
                "enable_assistant_ui": payload.enable_assistant_ui,
                "time_window_query": time_window_summary,
                "time_window_suggestions": context.get("time_window_suggestions", []),
                "conversation_history_count": len(conversation_history),
                "conversation_history_stats": conversation_history_stats,
                "session_summary_present": _has_meaningful_session_summary(session_summary_state),
                "session_summary_json_version": session_summary_state.get("version"),
                "session_summary_goal": session_summary_state.get("current_goal"),
                "session_summary_recent_topics": session_summary_state.get("recent_topics", []),
                "session_summary_time_preferences": session_summary_state.get("time_preferences", {}),
            }

            if payload.enable_web_search:
                output_text, web_search_sources = await generate_web_search_response(
                    payload.message,
                    context,
                    enable_assistant_ui=payload.enable_assistant_ui,
                )
                source_payload["web_search_sources"] = web_search_sources
                yield format_sse("source", source_payload)

                async for token in yield_text_in_chunks(output_text):
                    final_content.append(token)
                    yield format_sse("token", {"content": token})
            else:
                source_payload["web_search_sources"] = []
                yield format_sse("source", source_payload)

                async for token in stream_chat_tokens(
                    payload.message,
                    context,
                    enable_web_search=payload.enable_web_search,
                    enable_assistant_ui=payload.enable_assistant_ui,
                ):
                    final_content.append(token)
                    yield format_sse("token", {"content": token})

            context["web_search_sources"] = web_search_sources
            final_text = "".join(final_content)

            if audit_log_id is not None:
                await complete_ai_audit_log(audit_log_id, final_text)

            await insert_chat_message(
                session_id=session_id,
                role="assistant",
                message=final_text,
                metadata={
                    "request_id": request_id,
                    "citations": context.get("citations", []),
                    "pond_id": payload.pond_id,
                    "rag_retrieval": context.get("rag_retrieval", {}),
                    "use_rag": payload.use_rag,
                    "enable_web_search": payload.enable_web_search,
                    "enable_assistant_ui": payload.enable_assistant_ui,
                    "time_window_query": time_window_summary,
                    "time_window_suggestions": context.get("time_window_suggestions", []),
                    "conversation_history_count": len(conversation_history),
                    "conversation_history_stats": conversation_history_stats,
                    "session_summary_present": _has_meaningful_session_summary(session_summary_state),
                    "session_summary_json_version": session_summary_state.get("version"),
                    "web_search_sources": web_search_sources,
                },
            )

            try:
                updated_summary_state = build_session_summary_state(
                    previous_state=session_summary_state,
                    recent_messages=conversation_history,
                    latest_user_message=payload.message,
                    latest_assistant_message=final_text,
                    time_window_summary=time_window_summary,
                    context=context,
                    conversation_history_count=len(conversation_history),
                    conversation_history_stats=conversation_history_stats,
                )
                updated_summary_text = render_session_summary_text(
                    updated_summary_state,
                    settings.chat_session_summary_max_chars,
                )
                await update_chat_session_summary(session_id, updated_summary_text, updated_summary_state)
            except Exception as summary_update_err:
                warn("AI對話", f"更新 session 摘要失敗，但不影響本次回答：{summary_update_err}")

            yield format_sse("done", {"request_id": request_id, "session_id": session_id})
        except ValueError as err:
            if audit_log_id is not None:
                await fail_ai_audit_log(audit_log_id, str(err))
            yield format_sse("error", {"message": str(err)})
        except Exception as err:
            error("AI對話", err, request, {"request_id": request_id})
            if audit_log_id is not None:
                await fail_ai_audit_log(audit_log_id, str(err))
            yield format_sse("error", {"message": str(err)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
