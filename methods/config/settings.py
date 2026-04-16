import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _normalized_url(value: str | None, default: str) -> str:
    return (value or default).rstrip("/")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "rag-ai-helper")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = _as_int(os.getenv("APP_PORT"), 8000)
    app_env: str = os.getenv("APP_ENV", "development")
    allow_dev_auth_bypass: bool = _as_bool(os.getenv("ALLOW_DEV_AUTH_BYPASS"), False)

    database_url: str = os.getenv("DATABASE_URL", "127.0.0.1")
    database_port_rw: int = _as_int(os.getenv("DATABASE_PORT_RW"), 5432)
    database_port_ro: int = _as_int(os.getenv("DATABASE_PORT_RO"), 5432)
    database_name: str = os.getenv("DATABASE_NAME", "")
    database_user: str = os.getenv("DATABASE_USER", "")
    database_password: str = os.getenv("DATABASE_PASSWORD", "")
    database_ssl: bool = _as_bool(os.getenv("DATABASE_SSL"), False)

    ai_database_url: str = os.getenv("AI_DATABASE_URL", os.getenv("DATABASE_URL", "127.0.0.1"))
    ai_database_port: int = _as_int(os.getenv("AI_DATABASE_PORT"), 5432)
    ai_database_name: str = os.getenv("AI_DATABASE_NAME", "ai_helper_db")
    ai_database_user: str = os.getenv("AI_DATABASE_USER", os.getenv("DATABASE_USER", ""))
    ai_database_password: str = os.getenv("AI_DATABASE_PASSWORD", os.getenv("DATABASE_PASSWORD", ""))
    ai_database_ssl: bool = _as_bool(os.getenv("AI_DATABASE_SSL"), False)

    main_db_dsn: str = os.getenv("MAIN_DB_DSN", "")
    ai_db_dsn: str = os.getenv("AI_DB_DSN", "")

    redis_url: str = os.getenv("REDIS_URL", "")
    redis_key_prefix: str = os.getenv("REDIS_KEY_PREFIX", "fish-helper")
    web_jwt_secret: str = os.getenv("WEB_JWT_SECRET", "")
    expected_jwt_issuer: str = os.getenv("EXPECTED_JWT_ISSUER", "").strip()
    expected_jwt_audience: str = os.getenv("EXPECTED_JWT_AUDIENCE", "").strip()

    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    llm_base_url: str = _normalized_url(os.getenv("LLM_BASE_URL"), "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4.1-mini")
    llm_temperature: float = _as_float(os.getenv("LLM_TEMPERATURE"), 0.2)
    llm_max_retries: int = _as_int(os.getenv("LLM_MAX_RETRIES"), 2)
    llm_retry_base_seconds: float = _as_float(os.getenv("LLM_RETRY_BASE_SECONDS"), 2.0)

    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", os.getenv("LLM_PROVIDER", "ollama")).strip().lower()
    embedding_base_url: str = _normalized_url(
        os.getenv("EMBEDDING_BASE_URL"),
        os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", os.getenv("LLM_API_KEY", ""))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
    embedding_dimensions: int = _as_int(os.getenv("EMBEDDING_DIMENSIONS"), 0)

    cache_ttl_latest_summary: int = _as_int(os.getenv("CACHE_TTL_LATEST_SUMMARY"), 60)
    cache_ttl_trend_summary: int = _as_int(os.getenv("CACHE_TTL_TREND_SUMMARY"), 300)
    cache_ttl_rag_result: int = _as_int(os.getenv("CACHE_TTL_RAG_RESULT"), 900)
    chat_history_max_chars: int = _as_int(os.getenv("CHAT_HISTORY_MAX_CHARS"), 4000)
    chat_history_message_limit: int = _as_int(os.getenv("CHAT_HISTORY_MESSAGE_LIMIT"), 24)
    chat_session_summary_max_chars: int = _as_int(os.getenv("CHAT_SESSION_SUMMARY_MAX_CHARS"), 1200)

    rag_initial_candidate_limit: int = _as_int(os.getenv("RAG_INITIAL_CANDIDATE_LIMIT"), 20)
    rag_candidate_growth_step: int = _as_int(os.getenv("RAG_CANDIDATE_GROWTH_STEP"), 10)
    rag_max_expand_rounds: int = _as_int(os.getenv("RAG_MAX_EXPAND_ROUNDS"), 2)
    rag_max_context_papers: int = _as_int(os.getenv("RAG_MAX_CONTEXT_PAPERS"), 4)
    rag_max_chunks_per_paper: int = _as_int(os.getenv("RAG_MAX_CHUNKS_PER_PAPER"), 2)
    rag_neighbor_window: int = _as_int(os.getenv("RAG_NEIGHBOR_WINDOW"), 1)
    rag_min_distinct_papers: int = _as_int(os.getenv("RAG_MIN_DISTINCT_PAPERS"), 3)
    rag_min_total_chunks: int = _as_int(os.getenv("RAG_MIN_TOTAL_CHUNKS"), 6)
    rag_min_total_characters: int = _as_int(os.getenv("RAG_MIN_TOTAL_CHARACTERS"), 1800)
    time_window_max_days: int = _as_int(os.getenv("TIME_WINDOW_MAX_DAYS"), 31)
    time_window_max_points: int = _as_int(os.getenv("TIME_WINDOW_MAX_POINTS"), 500)


settings = Settings()
