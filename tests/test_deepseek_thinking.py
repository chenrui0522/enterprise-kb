from __future__ import annotations

from app.core.config import Settings
from app.providers.deepseek import DeepSeekProvider


def test_deepseek_thinking_disabled_by_default() -> None:
    settings = Settings(llm_api_key="test", llm_thinking_enabled=False)
    provider = DeepSeekProvider(settings)
    assert provider._thinking == {"type": "disabled"}
    kwargs = provider._create_kwargs(temperature=0.1)
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}


def test_deepseek_thinking_can_be_enabled() -> None:
    settings = Settings(llm_api_key="test", llm_thinking_enabled=True)
    provider = DeepSeekProvider(settings)
    assert provider._thinking == {"type": "enabled"}
    kwargs = provider._create_kwargs(temperature=None, stream=True)
    assert kwargs["stream"] is True
    assert kwargs["extra_body"]["thinking"] == {"type": "enabled"}
