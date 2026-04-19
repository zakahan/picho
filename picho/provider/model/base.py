"""
Provider Template
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from ..stream import EventStream, T, R
from ..types import Context, StreamOptions


class ProviderType(str, Enum):
    OPENAI_COMPLETION = "openai-completion"
    OPENAI_RESPONSES = "openai-responses"
    ARK_RESPONSES = "ark-responses"
    MOCK = "mock"
    CUSTOM = "custom"
    EMPTY = "empty"


InputType = Literal["text", "image", "video"]


@dataclass
class Model(ABC):
    model_name: str
    base_url: str
    model_provider: str = ProviderType.EMPTY
    api_key: str = ""
    api_key_env: str | None = None
    input_types: list[InputType] = field(default_factory=lambda: ["text"])
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.api_key:
            if self.api_key_env:
                self.api_key = os.getenv(self.api_key_env) or ""

    def require_api_key(self) -> str:
        if self.api_key:
            return self.api_key

        if self.api_key_env:
            self.api_key = os.getenv(self.api_key_env) or ""
            if not self.api_key:
                raise ValueError(
                    f"ApiKey required. Set `{self.api_key_env}` or pass api_key parameter."
                )
            return self.api_key

        raise ValueError("ApiKey required. please pass api_key parameter")

    @abstractmethod
    async def stream(
        self,
        context: Context,
        options: StreamOptions | None = None,
    ) -> EventStream[T, R]:
        pass
