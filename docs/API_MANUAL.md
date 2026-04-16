# API Manual

本文件說明目前 `rag-ai-helper` 的主要 API、SSE 事件格式，以及最新的上下文與時間窗行為。

## `GET /api/system/health`

檢查主要依賴是否可用。

範例回應：

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

列出指定使用者的歷史對話 session。

Query:

- `user_id`
  - 開發模式可傳
  - 正式模式建議改用 Bearer Token
- `limit`
  - 預設 `50`
  - 最大 `200`

---

## `GET /api/ai/sessions/{session_id}`

取得單一 session 與其對話訊息。

回應：

- `session`
- `messages`

`session` 目前包含：

- `summary`
- `summary_json`

---

## `DELETE /api/ai/sessions/{session_id}`

刪除單一 session 與其訊息。

---

## `POST /api/ai/chat/stream`

SSE 串流聊天 API。

### Request Body

```json
{
  "user_id": 3,
  "pond_id": 2,
  "session_id": "demo-session",
  "message": "最近 24 小時溶氧趨勢如何",
  "use_rag": true,
  "enable_web_search": false,
  "enable_assistant_ui": true,
  "time_window_from": "2026-04-10T00:00:00+08:00",
  "time_window_to": "2026-04-12T23:59:59+08:00",
  "compare_previous_window": false
}
```

### 欄位說明

- `use_rag`
  - 預設 `true`
  - `false` 時不做本地論文 RAG
- `enable_web_search`
  - 預設 `false`
  - 只有 `OpenAI` / `Gemini` provider 支援
- `enable_assistant_ui`
  - 預設 `true`
  - `true` 時後端會要求模型輸出適合 assistant-ui / Markdown 呈現的內容
  - `false` 時後端會要求模型回純文字
- `time_window_from` / `time_window_to`
  - 使用者手動指定時間窗
- `compare_previous_window`
  - `true` 時額外查詢前一個等長時間窗並比較

### SSE Event

- `start`
- `source`
- `token`
- `done`
- `error`

### `source` event 回傳欄位

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
  "session_summary_time_preferences": {},
  "autonomous_time_window_fetch": {
    "enabled": true,
    "executed_rounds": 1,
    "plans": []
  },
  "autonomous_time_window_trend": {
    "requested": true
  }
}
```

---

## `GET /api/rag/papers`

查詢目前 AI 資料庫中的論文來源。

---

## `GET /api/rag/ingest-jobs/{job_id}`

查詢論文匯入 / embedding 背景任務進度。

回應重點欄位：

- `status`
- `chunk_total`
- `embedded_chunks`
- `error_message`

---

## `POST /api/rag/embeddings/rebuild-all`

重建整庫 embedding。

```json
{
  "user_id": 3,
  "purge_current_model_embeddings": true,
  "purge_other_model_embeddings": false
}
```

---

## `POST /api/rag/papers/check-duplicate`

查重欄位：

- `doi`
- `file_hash`
- `content_hash`
- `title_normalized`
- `source_url`

Content-Type:

- `multipart/form-data`

---

## `POST /api/rag/papers`

上傳 PDF 並建立 chunk、embedding、背景任務。

Content-Type:

- `multipart/form-data`

欄位：

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

目前上下文採雙層記憶：

1. `session_summary_json`
   - 存在 `chat_sessions.summary_json`
   - 結構化長期記憶
2. `session_summary_text`
   - 由 `session_summary_json` 渲染成短文字
3. `conversation_history`
   - 最近原文對話
   - 先抓最多 `CHAT_HISTORY_MESSAGE_LIMIT`
   - 再用 `CHAT_HISTORY_MAX_CHARS` 裁切

### `session_summary_json` 欄位

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

---

## 時間窗查詢

### 使用者主動指定

前端可直接傳：

- `time_window_from`
- `time_window_to`
- `compare_previous_window`

### 後端語意解析

目前支援：

- `一天內`
- `最近 24 小時`
- `昨天`
- `昨天晚上`
- `今天`
- `上週`
- `上個月`
- `最近 7 天`
- `最近 30 天`
- `2026-04-10 到 2026-04-12`
- `最近 7 天和前 7 天比較`
- `那一天` / `那天` / `當天`

### `time_window_suggestions`

若問題涉及趨勢、比較、日夜差異，但沒有足夠明確的時間窗，後端會回：

- `time_window_suggestions`

前端應顯示時間選擇器供使用者直接選擇。

---

## 自主二次時間窗取數

目前聊天流程除了初始 `time_window_trend` 外，還支援模型自主要求再查一次感測資料時間窗。

### 目的

避免只靠自然語言拆解時間，讓模型在看完初始資料後，若判定證據不足，可以要求系統補查另一段時間資料。

### 運作方式

1. 先建立初始 context
2. 使用模型做一次「查詢規劃」
3. 若模型回傳需要更多時間窗資料：
   - 後端驗證請求
   - 查詢感測資料
   - 寫入 `autonomous_time_window_trend`
4. 再把完整 context 送給模型產生最終回答

### 限制

- `AUTONOMOUS_TIME_WINDOW_FETCH_ENABLED`
- `AUTONOMOUS_TIME_WINDOW_MAX_ROUNDS`
- `AUTONOMOUS_TIME_WINDOW_MAX_METRICS`
- `TIME_WINDOW_MAX_DAYS`
- `TIME_WINDOW_MAX_POINTS`

### 允許查詢的 metric

- `do_mg_l`
- `ph`
- `temp_deep`
- `temp_shallow`
- `turbidity_ntu`
- `orp_mv`

### 允許 bucket

- `10m`
- `hour`
- `day`

---

## 前端對接重點

- assistant-ui 應直接讀 `session_summary_json`
- `time_window_suggestions` 應顯示為時間選擇器或快捷按鈕
- `citations` 顯示為論文來源
- `web_search_sources` 顯示為網路搜索來源
- `autonomous_time_window_fetch` 可作為 debug / explain UI 顯示
- `enable_assistant_ui=false` 時，前端應改用純文字 renderer
