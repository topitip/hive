"""Entrypoint for the Hive HTTP API server in Docker."""

import json
import os
import sys
from pathlib import Path

# Add core/ to path so framework imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "core"))

from aiohttp import web

import framework.config as _hive_config
from framework.server.app import create_app

# Inject temperature into LLM calls via extra_kwargs
_original_get_extra = _hive_config.get_llm_extra_kwargs


def _patched_get_llm_extra_kwargs():
    kwargs = _original_get_extra()
    kwargs["temperature"] = float(os.environ.get("HIVE_TEMPERATURE", "0.3"))
    return kwargs


_hive_config.get_llm_extra_kwargs = _patched_get_llm_extra_kwargs


def _write_hive_config() -> None:
    """Generate ~/.hive/configuration.json from environment variables.

    The Hive framework reads LLM settings from this file.
    In Docker we generate it from env vars at startup.
    """
    api_base = os.environ.get("LITELLM_API_BASE", "")
    model = os.environ.get("HIVE_MODEL", "openai/gpt-oss-120b")

    # Split "provider/model" into parts
    parts = model.split("/", 1)
    provider = parts[0] if len(parts) == 2 else "openai"
    model_name = parts[1] if len(parts) == 2 else model

    config = {
        "llm": {
            "provider": provider,
            "model": model_name,
            "api_key_env_var": "LITELLM_API_KEY",
        }
    }
    if api_base:
        config["llm"]["api_base"] = api_base

    config_dir = Path.home() / ".hive"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "configuration.json"
    config_path.write_text(json.dumps(config, indent=2))


if __name__ == "__main__":
    _write_hive_config()

    model = os.environ.get("HIVE_MODEL", "openai/gpt-oss-120b")
    port = int(os.environ.get("HIVE_PORT", "8080"))

    app = create_app(model=model)
    web.run_app(app, host="0.0.0.0", port=port)
