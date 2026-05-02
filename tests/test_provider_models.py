from __future__ import annotations

from types import SimpleNamespace

import asyncio

from picho.provider.model.anthropic import AnthropicModel, to_anthropic_messages
from picho.provider.model.ark_responses import to_ark_messages
from picho.provider.model.factory import get_available_providers, get_model
from picho.provider.model.google import GoogleModel, to_google_messages
from picho.provider.model.openai_completion import (
    to_openai_messages as to_openai_completion_messages,
)
from picho.provider.model.openai_responses import (
    to_openai_messages as to_openai_responses_messages,
)
from picho.provider.types import (
    AssistantMessage,
    Context,
    ImageBase64Content,
    StopReason,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


class _FakePart:
    def __init__(
        self,
        *,
        text=None,
        inline_data=None,
        file_data=None,
        function_call=None,
        function_response=None,
    ):
        self.text = text
        self.inline_data = inline_data
        self.file_data = file_data
        self.function_call = function_call
        self.function_response = function_response

    @classmethod
    def from_text(cls, *, text: str):
        return cls(text=text)

    @classmethod
    def from_bytes(cls, *, data: bytes, mime_type: str):
        return cls(inline_data=SimpleNamespace(data=data, mime_type=mime_type))

    @classmethod
    def from_uri(cls, *, file_uri: str, mime_type=None):
        return cls(file_data=SimpleNamespace(file_uri=file_uri, mime_type=mime_type))

    @classmethod
    def from_function_call(cls, *, name: str, args: dict):
        return cls(function_call=SimpleNamespace(name=name, args=args))

    @classmethod
    def from_function_response(cls, *, name: str, response: dict, parts=None):
        del parts
        return cls(function_response=SimpleNamespace(name=name, response=response))


class _FakeContent:
    def __init__(self, *, role: str, parts: list[_FakePart]):
        self.role = role
        self.parts = parts


class _FakeGoogleTypes:
    Part = _FakePart
    Content = _FakeContent


def test_get_available_providers_includes_anthropic_and_google():
    providers = get_available_providers()

    assert "anthropic" in providers
    assert "google" in providers


def test_factory_creates_anthropic_model_with_defaults():
    model = get_model("anthropic")

    assert isinstance(model, AnthropicModel)
    assert model.model_name == "claude-sonnet-4-5"
    assert model.base_url == "https://api.anthropic.com"
    assert model.api_key_env == "ANTHROPIC_API_KEY"
    assert model.input_types == ["text", "image"]


def test_factory_creates_google_model_with_defaults():
    model = get_model("google")

    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-3-flash-preview"
    assert model.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert model.api_key_env == "GEMINI_API_KEY"
    assert model.input_types == ["text", "image"]


def test_openai_completion_messages_use_standard_tool_calls_shape():
    context = Context(
        instructions="System prompt",
        messages=[
            AssistantMessage(
                content=[
                    TextContent(type="text", text="Let me call a tool."),
                    ToolCall(
                        type="toolCall",
                        id="call_1",
                        name="lookup_weather",
                        arguments={"city": "Beijing"},
                    ),
                ],
                provider="openai-completion",
                model="gpt-4o",
                stop_reason=StopReason.TOOL_USE,
            )
        ],
    )

    messages = to_openai_completion_messages(context, ["text"])

    assert messages == [
        {"role": "system", "content": "System prompt"},
        {
            "role": "assistant",
            "content": "Let me call a tool.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup_weather",
                        "arguments": '{"city": "Beijing"}',
                    },
                }
            ],
        },
    ]


def test_provider_messages_preserve_dict_text_tool_results():
    context = Context(
        messages=[
            ToolResultMessage(
                tool_call_id="call_1|opaque",
                tool_name="webfetch",
                is_error=False,
                content=[
                    {
                        "type": "text",
                        "text": "Read status: success\nDocument text.",
                    }
                ],
            )
        ],
    )

    completion_messages = to_openai_completion_messages(context, ["text"])
    assert completion_messages == [
        {
            "role": "tool",
            "tool_call_id": "call_1|opaque",
            "content": "Read status: success\nDocument text.",
        }
    ]

    openai_responses_messages, _ = to_openai_responses_messages(context, ["text"])
    assert openai_responses_messages == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Read status: success\nDocument text.",
        }
    ]

    ark_messages, _ = asyncio.run(to_ark_messages(context, ["text"]))
    assert ark_messages == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Read status: success\nDocument text.",
        }
    ]
    assert "(see attached image)" not in ark_messages[0]["output"]


def test_anthropic_messages_convert_tool_result_images():
    context = Context(
        instructions="Be helpful",
        messages=[
            ToolResultMessage(
                tool_call_id="call_1|opaque",
                tool_name="inspect_image",
                is_error=False,
                content=[
                    TextContent(type="text", text="Found an issue."),
                    ImageBase64Content(
                        type="image_base64",
                        data="aGVsbG8=",
                        mime_type="image/png",
                    ),
                ],
            )
        ],
    )

    messages, instructions = to_anthropic_messages(context, ["text", "image"])

    assert instructions == "Be helpful"
    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": [
                        {"type": "text", "text": "Found an issue."},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "aGVsbG8=",
                            },
                        },
                    ],
                    "is_error": False,
                }
            ],
        }
    ]


def test_google_messages_convert_tool_history_and_user_image():
    context = Context(
        instructions="Be helpful",
        messages=[
            UserMessage(
                content=[
                    TextContent(type="text", text="Describe this image"),
                    ImageBase64Content(
                        type="image_base64",
                        data="aGVsbG8=",
                        mime_type="image/png",
                    ),
                ]
            ),
            AssistantMessage(
                content=[
                    ToolCall(
                        type="toolCall",
                        id="call_2",
                        name="inspect_image",
                        arguments={"mode": "brief"},
                    )
                ],
                provider="google",
                model="gemini-3-flash-preview",
            ),
            ToolResultMessage(
                tool_call_id="call_2",
                tool_name="inspect_image",
                content=[TextContent(type="text", text="Image looks fine.")],
            ),
        ],
    )

    messages = to_google_messages(context, ["text", "image"], _FakeGoogleTypes)

    assert len(messages) == 3
    assert messages[0].role == "user"
    assert messages[0].parts[0].text == "Describe this image"
    assert messages[0].parts[1].inline_data.mime_type == "image/png"
    assert messages[1].role == "model"
    assert messages[1].parts[0].function_call.name == "inspect_image"
    assert messages[2].role == "tool"
    assert messages[2].parts[0].function_response.name == "inspect_image"
    assert messages[2].parts[0].function_response.response == {
        "content": "Image looks fine.",
        "is_error": False,
    }
