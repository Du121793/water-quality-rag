# 部署手冊

## 1. 建立環境

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. 設定環境變數

將 `example.env` 複製為 `.env`，至少填好以下欄位：

- `DATABASE_URL`
- `DATABASE_PORT_RO`
- `DATABASE_NAME`
- `DATABASE_USER`
- `DATABASE_PASSWORD`
- `AI_DATABASE_URL`
- `AI_DATABASE_PORT`
- `AI_DATABASE_NAME`
- `AI_DATABASE_USER`
- `AI_DATABASE_PASSWORD`
- `REDIS_URL`
- `WEB_JWT_SECRET`

## 3. LLM Provider 設定

聊天模型目前支援三種 provider：

- `ollama`
- `openai`
- `gemini`

### Ollama

```env
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
LLM_DEFAULT_MODEL=qwen2.5:7b-instruct
```

### OpenAI

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-openai-api-key
LLM_DEFAULT_MODEL=gpt-5.4-nano
```

### Gemini

```env
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta
LLM_API_KEY=your-gemini-api-key
LLM_DEFAULT_MODEL=gemini-3-flash
```

## 4. Embedding Provider 設定

RAG 向量化與聊天模型分開設定，方便之後切 OpenAI 或 Gemini。

### Ollama

```env
EMBEDDING_PROVIDER=ollama
EMBEDDING_BASE_URL=http://127.0.0.1:11434
EMBEDDING_API_KEY=
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=0
```

### OpenAI

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=your-openai-api-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

### Gemini

```env
EMBEDDING_PROVIDER=gemini
EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
EMBEDDING_API_KEY=your-gemini-api-key
EMBEDDING_MODEL=text-embedding-004
EMBEDDING_DIMENSIONS=768
```

## 5. 模型能力配置 (model_config.json)

專案根目錄下必須存在 `model_config.json` 檔案。此檔案負責定義各個模型是否啟用，以及其支援的進階功能（例如深度思考與多模態）。

- **切換可用模型**：將模型屬性中的 `"enabled": true` 即可讓該模型在前端列表中出現。
- **深度思考 (Deep Thinking)**：透過 `"supports_deep_thinking": true` 及 `"deep_thinking_level"` 來控制各模型的預設思考強度。
- **多模態 (Multimodal)**：透過 `"supports_multimodal": true` 控制是否允許圖片/檔案上傳。

**注意**：`.env` 中的 `LLM_DEFAULT_MODEL` 必須是 `model_config.json` 中有定義且 `enabled` 為 `true` 的模型。

## 6. 啟動 AI 向量資料庫

本專案建議主資料庫維持既有 Patroni 叢集不動，AI 向量資料庫獨立以 Docker 部署。

```bash
docker compose -f docker-compose.ai-db.yml up -d
```

預設連線資訊：

- Host: `127.0.0.1`
- Port: `5433`
- Database: `ai_helper_db`
- User: `dev`

## 7. 建立 AI DB Schema

```bash
psql postgresql://dev:asdasd@127.0.0.1:5433/ai_helper_db -f build/buildDB.sql
```

## 8. 匯入論文與建立向量

先匯入 PDF 文字：

```bash
.venv\Scripts\python scripts/ingest_water_quality_papers.py
```

再建立論文 embedding：

```bash
.venv\Scripts\python scripts/embed_paper_chunks.py
```

## 9. Redis

Redis 為必要元件，用於：

- 魚池上下文快取
- RAG 查詢結果快取
- 降低重複查詢主資料庫與 AI DB 的成本

## 10. 啟動服務

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 11. 驗證端點

- `GET /api/system/health`
- `GET /api/ai/models`
- `POST /api/ai/chat/stream`
