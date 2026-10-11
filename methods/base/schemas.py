from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Attachment(BaseModel):
    name: str | None = Field(default=None, description="原始附件檔案名稱。")
    type: str = Field(description="附件類型，如 'image' 或 'file'。")
    mime_type: str | None = Field(default=None, description="MIME 類型，例如 'image/png'。")
    data: str | None = Field(default=None, description="Base64 編碼的內容。")
    url: str | None = Field(default=None, description="檔案或圖片的 URL。")


class ChatStreamRequest(BaseModel):
    user_id: int | None = Field(default=None, description="開發模式可直接傳入 user_id。")
    pond_id: int = Field(description="魚池 ID。")
    session_id: str | None = Field(default=None, description="對話 session ID。")
    model: str | None = Field(default=None, description="覆蓋預設使用的模型名稱。")
    message: str = Field(min_length=1, description="使用者訊息內容。")
    attachments: list[Attachment] = Field(default_factory=list, description="圖片或檔案附件。")
    use_rag: bool = Field(default=True, description="是否啟用本地論文 RAG。")
    deep_thinking: bool = Field(default=False, description="是否啟用深度思考 (Reasoning)。")
    enable_web_search: bool = Field(default=False, description="是否啟用模型端網路搜索。")
    enable_assistant_ui: bool = Field(default=True, description="是否輸出適合 assistant-ui 呈現的內容。")
    time_window_from: datetime | None = Field(default=None, description="手動指定時間窗起點。")
    time_window_to: datetime | None = Field(default=None, description="手動指定時間窗終點。")
    compare_previous_window: bool = Field(default=False, description="是否同時比較前一個等長時間窗。")


class RebuildEmbeddingsRequest(BaseModel):
    user_id: int | None = Field(default=None, description="開發模式可直接傳入 user_id。")
    purge_current_model_embeddings: bool = Field(
        default=True,
        description="是否先刪除目前 embedding provider/model 的既有向量。",
    )
    purge_other_model_embeddings: bool = Field(
        default=False,
        description="是否一併刪除其他 provider/model 的向量。",
    )
