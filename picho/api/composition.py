import asyncio
import json
import time
from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from ..agent import AgentEvent
from ..provider.types import (
    ImageBase64Content,
    ImageUrlContent,
    Message,
    TextContent,
    UserMessage,
)
from ..runner import Runner


class APIAppBuilder:
    def __init__(self, title: str):
        self._app = FastAPI(title=title)

    @property
    def app(self) -> FastAPI:
        return self._app

    def add_middleware(self, middleware_class: Any, **kwargs: Any) -> "APIAppBuilder":
        self._app.add_middleware(middleware_class, **kwargs)
        return self

    def add_bundle(self, bundle: Any) -> "APIAppBuilder":
        bundle.register(self._app)
        return self

    def build(self) -> FastAPI:
        return self._app


class CoreRoutesBundle:
    def register(self, app: FastAPI) -> None:
        @app.get("/health")
        async def health():
            return {"status": "ok"}


class SessionAPIAdapter:
    async def validate_run_request(self, req: Any) -> None:
        return None

    async def on_run_start(self, req: Any) -> tuple[Any, list[dict[str, Any]]]:
        return None, []

    async def on_run_complete(self, req: Any, run_state: Any) -> list[dict[str, Any]]:
        return []

    async def on_run_cancelled(self, req: Any, run_state: Any) -> list[dict[str, Any]]:
        return []

    async def on_run_error(
        self,
        req: Any,
        run_state: Any,
        error: Exception,
    ) -> list[dict[str, Any]]:
        return []

    async def convert_message(
        self, req_message: Any, req: Any | None = None
    ) -> Message:
        content = req_message.content
        if isinstance(content, str):
            return UserMessage(content=[TextContent(type="text", text=content)])

        parts = []
        for part in content:
            part_dict = part.model_dump() if hasattr(part, "model_dump") else dict(part)
            if part_dict.get("type") == "text":
                parts.append(TextContent(type="text", text=part_dict.get("text", "")))
            elif part_dict.get("type") == "image_base64":
                parts.append(
                    ImageBase64Content(
                        type="image_base64",
                        data=part_dict.get("data", ""),
                        mime_type=part_dict.get("mime_type", "image/png"),
                    )
                )
            elif part_dict.get("type") == "image_url":
                parts.append(
                    ImageUrlContent(
                        type="image_url",
                        url=part_dict.get("url", ""),
                    )
                )

        return UserMessage(content=parts)

    def extract_messages(self, state: Any) -> list[dict]:
        if not state:
            return []
        entries = state.session.get_entries()
        messages = []
        for entry in entries:
            if hasattr(entry, "message"):
                messages.append(entry.message)
        return messages

    def serialize_event(self, event: AgentEvent) -> dict[str, Any]:
        data: dict[str, Any] = {"type": event.type, "timestamp": time.time()}

        if event.type in {"thinking_delta", "content_delta"}:
            if event.assistant_event and hasattr(event.assistant_event, "data"):
                delta = getattr(event.assistant_event.data, "delta", "")
                if delta:
                    data["content"] = delta
        elif event.type == "tool_execution_start":
            data["tool_call_id"] = event.tool_call_id
            data["tool_name"] = event.tool_name
            data["args"] = event.args
        elif event.type == "tool_execution_end":
            data["tool_call_id"] = event.tool_call_id
            data["tool_name"] = event.tool_name
            data["result"] = self.serialize_result(event.result)
            data["is_error"] = event.is_error
        elif event.type == "message_end" and event.message:
            data["message"] = self.serialize_message(event.message)

        return data

    def serialize_result(self, result: Any) -> Any:
        if result is None:
            return None
        if isinstance(result, str):
            return result
        if hasattr(result, "content"):
            contents = []
            for content_block in result.content:
                if hasattr(content_block, "text"):
                    contents.append(content_block.text)
            return "\n".join(contents) if contents else str(result)
        return str(result)

    def serialize_message(self, message: Message) -> dict[str, Any]:
        if hasattr(message, "to_dict"):
            return message.to_dict()
        if hasattr(message, "__dataclass_fields__"):
            return asdict(message)
        return dict(message)

    def to_sse_event(self, data: dict[str, Any]) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class SessionRouteBundle:
    def __init__(
        self,
        runner: Runner,
        adapter: SessionAPIAdapter,
        create_session_request_model: Any,
        request_message_model: Any,
        run_request_model: Any,
    ):
        self.runner = runner
        self.adapter = adapter
        self.create_session_request_model = create_session_request_model
        self.request_message_model = request_message_model
        self.run_request_model = run_request_model

    def register(self, app: FastAPI) -> None:
        CreateSessionRequestModel = self.create_session_request_model
        RequestMessageModel = self.request_message_model
        RunRequestModel = self.run_request_model

        @app.post("/sessions")
        async def create_session(req: CreateSessionRequestModel | None = None):
            session_id = req.session_id if req else None
            try:
                sid = self.runner.create_session(session_id)
                return {"session_id": sid}
            except ValueError as e:
                raise HTTPException(400, str(e))

        @app.get("/sessions/{session_id}")
        async def get_session(session_id: str):
            if not self.runner.has_session(session_id):
                raise HTTPException(404, f"Session not found: {session_id}")
            state = self.runner.get_session(session_id)
            return {
                "session_id": session_id,
                "messages": self.adapter.extract_messages(state),
            }

        @app.get("/sessions")
        async def list_sessions():
            sessions = self.runner.list_sessions()
            return [
                {
                    "session_id": session["session_id"],
                    "message_count": session["entry_count"],
                }
                for session in sessions
            ]

        @app.delete("/sessions/{session_id}")
        async def delete_session(session_id: str):
            if not self.runner.delete_session(session_id):
                raise HTTPException(404, f"Session not found: {session_id}")
            return None

        @app.post("/sessions/{session_id}/abort")
        async def abort_session(session_id: str):
            if not self.runner.has_session(session_id):
                raise HTTPException(404, f"Session not found: {session_id}")

            is_streaming = self.runner.is_streaming(session_id)
            self.runner.abort(session_id)
            return {
                "session_id": session_id,
                "status": "aborting" if is_streaming else "idle",
            }

        @app.post("/sessions/{session_id}/steer")
        async def steer_session(
            session_id: str, req_message: RequestMessageModel = Body(...)
        ):
            if not self.runner.has_session(session_id):
                raise HTTPException(404, f"Session not found: {session_id}")

            message = await self.adapter.convert_message(req_message)
            self.runner.steer(session_id, message)
            return {"session_id": session_id, "status": "queued"}

        @app.post("/run_sse")
        async def run_sse(req: RunRequestModel = Body(...)):
            if not self.runner.has_session(req.session_id):
                raise HTTPException(404, f"Session not found: {req.session_id}")
            await self.adapter.validate_run_request(req)
            return StreamingResponse(
                self._event_generator(req),
                media_type="text/event-stream",
            )

    async def _event_generator(self, req: Any):
        event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        run_state = None

        def on_event(event: AgentEvent):
            event_queue.put_nowait(event)

        unsubscribe = self.runner.subscribe(req.session_id, on_event)

        try:
            run_state, initial_events = await self.adapter.on_run_start(req)
            for event_data in initial_events:
                yield self.adapter.to_sse_event(event_data)

            message = await self.adapter.convert_message(req.message, req=req)
            prompt_task = asyncio.create_task(
                self.runner.prompt(req.session_id, message)
            )

            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    yield self.adapter.to_sse_event(
                        {
                            "type": "error",
                            "message": "Timeout waiting for event",
                            "timestamp": time.time(),
                        }
                    )
                    break

                yield self.adapter.to_sse_event(self.adapter.serialize_event(event))

                if event.type == "agent_end":
                    break

            await prompt_task

            for event_data in await self.adapter.on_run_complete(req, run_state):
                yield self.adapter.to_sse_event(event_data)

        except asyncio.CancelledError:
            for event_data in await self.adapter.on_run_cancelled(req, run_state):
                yield self.adapter.to_sse_event(event_data)
            yield self.adapter.to_sse_event(
                {
                    "type": "error",
                    "message": "Request cancelled",
                    "timestamp": time.time(),
                }
            )
        except Exception as e:
            for event_data in await self.adapter.on_run_error(req, run_state, e):
                yield self.adapter.to_sse_event(event_data)
            yield self.adapter.to_sse_event(
                {
                    "type": "error",
                    "message": str(e),
                    "timestamp": time.time(),
                }
            )
        finally:
            unsubscribe()
