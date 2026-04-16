from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    user_id: int | None = Field(default=None, description="開發模式可直接傳入的使用者 ID")
    pond_id: int = Field(description="魚池 ID")
    session_id: str | None = Field(default=None, description="對話 Session ID")
    message: str = Field(min_length=1, description="使用者提問內容")
    use_rag: bool = Field(default=True, description="是否啟用本地論文 RAG")
    enable_web_search: bool = Field(default=False, description="是否啟用外部網路搜尋")
    enable_assistant_ui: bool = Field(
        default=True,
        description="是否啟用 assistant-ui / Markdown 風格輸出",
    )
    time_window_from: datetime | None = Field(
        default=None,
        description="指定查詢時間窗起點，ISO 8601 格式",
    )
    time_window_to: datetime | None = Field(
        default=None,
        description="指定查詢時間窗終點，ISO 8601 格式",
    )
    compare_previous_window: bool = Field(
        default=False,
        description="是否同時比較前一個等長時間窗",
    )


class RebuildEmbeddingsRequest(BaseModel):
    user_id: int | None = Field(default=None, description="開發模式可直接傳入的使用者 ID")
    purge_current_model_embeddings: bool = Field(
        default=True,
        description="是否清除目前 embedding provider/model 的既有向量",
    )
    purge_other_model_embeddings: bool = Field(
        default=False,
        description="是否一併清除其他 embedding provider/model 的向量",
    )
