import json
import os
from pathlib import Path
from typing import Any, TypedDict

class ModelCapability(TypedDict):
    provider: str
    enabled: bool
    supports_deep_thinking: bool
    thinking_type: str  # "openai_effort", "gemini_budget", "gemini_level", "none"
    deep_thinking_level: str  # "minimal", "low", "medium", "high", "xhigh"
    supports_multimodal: bool
    disallow_temperature: bool
    family: str

def load_config() -> dict[str, ModelCapability]:
    # 設定位置固定在專案根目錄，避免從其他目錄啟動時讀不到模型。
    config_path = Path(__file__).resolve().parents[2] / "model_config.json"
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_model_capability(model_name: str) -> ModelCapability:
    config = load_config()
    
    # 精確匹配
    if model_name in config:
        return config[model_name]
    
    # 模糊匹配
    for key, capability in config.items():
        if model_name.lower().startswith(key.lower()):
            return capability
    
    # 預設通用配置
    return {
        "provider": "unknown",
        "enabled": False,
        "supports_deep_thinking": False,
        "thinking_type": "none",
        "deep_thinking_level": "medium",
        "supports_multimodal": False,
        "disallow_temperature": False,
        "family": "unknown",
    }
