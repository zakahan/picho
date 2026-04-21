from typing import Any

from .base import Model, ProviderType, InputType
from ...logger import get_logger

_log = get_logger(__name__)


def get_model(
    model_provider: str,
    model_name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    input_types: list[InputType] | None = None,
    extra: dict[str, Any] | None = None,
) -> Model:
    _log.info(
        f"Creating model: provider={model_provider} model_name={model_name} base_url={base_url}"
    )

    if model_provider == ProviderType.ARK_RESPONSES.value:
        from .ark_responses import (
            ArkResponsesModel,
            default_ark_model,
            default_ark_base_url,
            default_ark_env,
        )

        return ArkResponsesModel(
            model_name=model_name or default_ark_model,
            base_url=base_url or default_ark_base_url,
            api_key=api_key,
            api_key_env=default_ark_env,
            model_provider=ProviderType.ARK_RESPONSES.value,
            input_types=input_types or ["text"],
            extra=extra or {},
        )

    elif model_provider == ProviderType.OPENAI_COMPLETION.value:
        from .openai_completion import (
            OpenAICompletionModel,
            default_openai_model,
            default_openai_base_url,
            default_openai_env,
        )

        return OpenAICompletionModel(
            model_name=model_name or default_openai_model,
            base_url=base_url or default_openai_base_url,
            api_key=api_key,
            api_key_env=default_openai_env,
            model_provider=ProviderType.OPENAI_COMPLETION.value,
            input_types=input_types or ["text"],
            extra=extra or {},
        )

    elif model_provider == ProviderType.OPENAI_RESPONSES.value:
        from .openai_responses import (
            OpenAIResponsesModel,
            default_openai_model,
            default_openai_base_url,
            default_openai_env,
        )

        return OpenAIResponsesModel(
            model_name=model_name or default_openai_model,
            base_url=base_url or default_openai_base_url,
            api_key=api_key,
            api_key_env=default_openai_env,
            model_provider=ProviderType.OPENAI_RESPONSES.value,
            input_types=input_types or ["text"],
            extra=extra or {},
        )
    elif model_provider == ProviderType.ANTHROPIC.value:
        from .anthropic import (
            AnthropicModel,
            default_anthropic_model,
            default_anthropic_base_url,
            default_anthropic_env,
        )

        return AnthropicModel(
            model_name=model_name or default_anthropic_model,
            base_url=base_url or default_anthropic_base_url,
            api_key=api_key,
            api_key_env=default_anthropic_env,
            model_provider=ProviderType.ANTHROPIC.value,
            input_types=input_types or ["text", "image"],
            extra=extra or {},
        )
    elif model_provider == ProviderType.GOOGLE.value:
        from .google import (
            GoogleModel,
            default_google_model,
            default_google_base_url,
            default_google_env,
        )

        return GoogleModel(
            model_name=model_name or default_google_model,
            base_url=base_url or default_google_base_url,
            api_key=api_key,
            api_key_env=default_google_env,
            model_provider=ProviderType.GOOGLE.value,
            input_types=input_types or ["text", "image"],
            extra=extra or {},
        )
    elif model_provider == ProviderType.MOCK.value:
        from .mock import MockModel, default_mock_model, default_mock_base_url

        return MockModel(
            model_name=model_name or default_mock_model,
            base_url=base_url or default_mock_base_url,
            api_key=api_key or "",
            api_key_env=None,
            model_provider=ProviderType.MOCK.value,
            input_types=input_types or ["text"],
            extra=extra or {},
        )

    elif model_provider == ProviderType.CUSTOM.value:
        raise NotImplementedError(f"Provider {model_provider} not implemented yet")
    elif model_provider == ProviderType.EMPTY.value:
        raise NotImplementedError(f"Provider {model_provider} not implemented yet")
    else:
        raise ValueError(f"Unknown provider: {model_provider}")


def get_available_providers() -> list[str]:
    return [
        ProviderType.ARK_RESPONSES.value,
        ProviderType.OPENAI_COMPLETION.value,
        ProviderType.OPENAI_RESPONSES.value,
        ProviderType.ANTHROPIC.value,
        ProviderType.GOOGLE.value,
        ProviderType.MOCK.value,
    ]
