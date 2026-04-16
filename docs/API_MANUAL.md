# API Manual

這份文件說明目前 AI Helper 的對外 API 與上下文策略。

## `GET /api/system/health`

健康檢查。

回應範例：
```json
{
  "success": true,
  "data": {
    "main_db": true,
    "ai_db": true,
    "redis": true
  }
}
```

---

## `GET /api/ai/sessions`

列出使用者的歷史對話 session。

Query：
- `user_id`：開發模式可帶，正式模式走 Bearer Token
- `limit`：預設 50，最大 200

---

## `GET /api/ai/sessions/{session_id}`

取得單一 session 與其訊息。

Query：
- `user_id`：開發模式可帶，正式模式走 Bearer Token

回應內容：
- `session`
- `messages`

`session` 目前會包含：
- `summary`
- `summary_json`

---

## `DELETE /api/ai/sessions/{session_id}`

刪除單一 session 與其訊息。

Query：
- `user_id`：開發模式可帶，正式模式走 Bearer Token

---

## `POST /api/ai/chat/stream`

SSE 串流聊天接口。

### Request Body

```json
{
  "user_id": 3,
  "pond_id": 2,
  "session_id": "demo-session",
  "message": "最近這個魚池溶氧狀況如何",
  "use_rag": true,
  "enable_web_search": false,
  "enable_assistant_ui": true,
  "time_window_from": "2026-04-10T00:00:00+08:00",
  "time_window_to": "2026-04-12T23:59:59+08:00",
  "compare_previous_window": false
}
```

### 參數說明

- `use_rag`
  - 預設 `true`
  - `false` 時不查論文 RAG
- `enable_web_search`
  - 預設 `false`
  - 只支援 `OpenAI` / `Gemini`
- `enable_assistant_ui`
  - 預設 `true`
  - `true` 時允許 Markdown / assistant-ui 風格輸出
  - `false` 時要求純文字輸出
- `time_window_from` / `time_window_to`
  - 明確指定時間窗
- `compare_previous_window`
  - `true` 時會自動做前一窗口比較

### SSE Event

- `start`
- `source`
- `token`
- `done`
- `error`

### `source` event 內容

```json
{
  "pond_name": "1",
  "paper_count": 4,
  "citations": [],
  "web_search_sources": [],
  "rag_retrieval": {},
  "use_rag": true,
  "enable_web_search": false,
  "enable_assistant_ui": true,
  "time_window_query": {},
  "time_window_suggestions": [],
  "conversation_history_count": 0,
  "conversation_history_stats": {},
  "session_summary_present": true,
  "session_summary_json_version": 1,
  "session_summary_goal": "追蹤魚池溶氧",
  "session_summary_recent_topics": ["魚池", "溶氧"],
  "session_summary_time_preferences": {}
}
```

---

## `GET /api/rag/papers`

查詢 AI 資料庫中的論文索引。

---

## `GET /api/rag/ingest-jobs/{job_id}`

查詢論文匯入與 embedding 背景任務進度。

回傳欄位：
- `status`
- `chunk_total`
- `embedded_chunks`
- `error_message`

---

## `POST /api/rag/embeddings/rebuild-all`

整庫重建 embedding。

### Request Body

```json
{
  "user_id": 3,
  "purge_current_model_embeddings": true,
  "purge_other_model_embeddings": false
}
```

---

## `POST /api/rag/papers/check-duplicate`

查重論文，支援：
- `doi`
- `file_hash`
- `content_hash`
- `title_normalized`
- `source_url`

Content-Type：
- `multipart/form-data`

---

## `POST /api/rag/papers`

上傳 PDF 並建立論文、chunk 與 embedding 背景任務。

Content-Type：
- `multipart/form-data`

主要欄位：
- `file`
- `title`
- `source_url`
- `doi`
- `authors`
- `journal_name`
- `published_at`
- `duplicate_policy`
- `operator_user_id`

---

## Context Memory v2

目前對話上下文分成三層：

1. `session_summary_json`
   - 保存在 `chat_sessions.summary_json`
   - 是結構化長期記憶
2. `session_summary_text`
   - 由 `session_summary_json` 渲染出的短摘要
3. `conversation_history`
   - 同一個 session 最近的訊息
   - 先抓候選，再用字元預算裁切

### `session_summary_json` 建議欄位

- `version`
- `updated_at`
- `current_goal`
- `confirmed_facts`
- `open_questions`
- `recent_topics`
- `time_preferences`
- `important_metrics`
- `assistant_state`
- `legacy_summary_text`

### 對話歷史策略

- `CHAT_HISTORY_MESSAGE_LIMIT`
  - 候選訊息數，不是最終送進模型的固定筆數
  - 預設 24
- `CHAT_HISTORY_MAX_CHARS`
  - 實際送進模型的對話字元預算
- `CHAT_SESSION_SUMMARY_MAX_CHARS`
  - `session_summary_text` 的輸出上限

### 時間窗策略

模型可以自行解析：
- `最近 7 天`
- `昨天晚上`
- `2026-04-10 到 2026-04-12`
- `最近 7 天和前 7 天比較`

如果問題不夠明確，`source` event 會帶：
- `time_window_suggestions`

前端可讓使用者直接選：
- `time_window_from`
- `time_window_to`
- `compare_previous_window`

---

## 擬變更內容

以下是目前系統規劃與已落地的對接準則，前後端請以此為準。

- `chat_sessions.summary` 保留短文字摘要。
- `chat_sessions.summary_json` 保留結構化長期記憶。
- `conversation_history` 不再固定 12 筆直出，而是先抓候選再按字元預算裁切。
- `time_window_suggestions` 會在問題時間不明確時提供給前端。
- `enable_assistant_ui=false` 時，模型輸出會被限制為純文字。
- `enable_web_search=true` 時，外部搜尋來源會額外列在 `web_search_sources`。
- `session_summary_json` 會持續更新，供下一輪對話續接。

---

## 建議的前端行為

- `assistant-ui` 直接渲染 `session_summary_json`
- 有 `time_window_suggestions` 時顯示時間選擇器
- `citations` 顯示論文引用
- `web_search_sources` 顯示網路搜尋來源
- 當 `enable_assistant_ui=false` 時，直接用純文字 renderer
