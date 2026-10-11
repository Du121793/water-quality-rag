# API Manual

本文件說明目前 `rag-ai-helper` 的主要 API、SSE 事件格式，以及最新的上下文與時間窗行為。

## `GET /api/system/health`

檢查主要依賴（資料庫、Redis）是否可用。

---

## `GET /api/ai/models` (新增)

列出後端 `model_config.json` 中已標註為 `enabled: true` 的可用模型清單。前端應以此清單構建模型選擇器。

回應範例：
```json
{
  "success": true,
  "data": {
    "gpt-5.4-nano": {
      "provider": "openai",
      "enabled": true,
      "supports_deep_thinking": true,
      "thinking_type": "openai_effort",
      "supports_multimodal": true,
      "family": "gpt-5.4"
    }
  }
}
```

---

## `GET /api/ai/sessions`

列出指定使用者的歷史對話 session。

---

## `POST /api/ai/chat/stream`

SSE 串流聊天 API。

### Request Body

```json
{
  "user_id": 3,
  "pond_id": 2,
  "session_id": "demo-session",
  "model": "gpt-5.4-nano",
  "message": "這張圖片裡的設備正常嗎？",
  "attachments": [
    {
      "type": "image",
      "mime_type": "image/png",
      "data": "base64_encoded_string..."
    }
  ],
  "deep_thinking": true,
  "use_rag": true,
  "enable_web_search": false,
  "enable_assistant_ui": true
}
```

### 欄位說明

- `model` (新增)
  - 可選。指定要使用的模型名稱。若未傳入，將使用 `.env` 中的 `LLM_DEFAULT_MODEL`。
- `attachments` (新增)
  - 附件列表。後端會根據模型是否 `supports_multimodal` 自動過濾。
  - `type`: `image` 或 `file`。
- `deep_thinking` (新增)
  - 預設 `false`。開啟推理/深度思考模式。
- `use_rag`
  - 預設 `true`。是否使用本地論文庫。
- `enable_web_search`
  - 預設 `false`。是否啟用模型端網路搜索。

---

## 模型能力配置 (`model_config.json`)

位於專案根目錄，控制後端如何與不同 LLM 溝通。

### 核心參數
- `enabled`: 只有設為 `true` 的模型會出現在 `/api/ai/models` 且允許前端指定。
- `supports_multimodal`: 若為 `false`，後端會自動剔除 `attachments` 以防止 API 報錯。
- `supports_deep_thinking`: 是否允許注入推理參數。

### 環境變數變更
- **`LLM_DEFAULT_MODEL`**: 原 `LLM_MODEL` 已更名，用於設定系統預設模型。

---

## SSE 事件與其他 API
(其餘 SSE 事件 `start`, `source`, `token`, `done` 等行為保持不變，請參考先前版本文件。)
