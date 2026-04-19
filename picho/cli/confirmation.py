"""
Confirmation manager for dangerous operations

Provides a mechanism for callbacks to request user confirmation
before executing dangerous operations (like rm, mv, etc.)
"""

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Any, Awaitable, Union
from enum import Enum


class ConfirmationStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ConfirmationRequest:
    id: str
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    response_event: asyncio.Event = field(default_factory=asyncio.Event)

    def approve(self):
        self.status = ConfirmationStatus.APPROVED
        self.response_event.set()

    def reject(self):
        self.status = ConfirmationStatus.REJECTED
        self.response_event.set()

    async def wait_for_response(self, timeout: float | None = None) -> bool:
        try:
            if timeout:
                await asyncio.wait_for(self.response_event.wait(), timeout=timeout)
            else:
                await self.response_event.wait()
        except asyncio.TimeoutError:
            self.status = ConfirmationStatus.REJECTED
        return self.status == ConfirmationStatus.APPROVED


class ConfirmationManager:
    def __init__(self):
        self._pending_request: ConfirmationRequest | None = None
        self._on_request: (
            Callable[[ConfirmationRequest], Union[None, Awaitable[None]]] | None
        ) = None
        self._lock = asyncio.Lock()

    def set_on_request(
        self, callback: Callable[[ConfirmationRequest], Union[None, Awaitable[None]]]
    ):
        self._on_request = callback

    async def request_confirmation(
        self,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> bool:
        async with self._lock:
            request_id = f"confirm_{id(self)}"
            request = ConfirmationRequest(
                id=request_id,
                title=title,
                message=message,
                details=details or {},
            )
            self._pending_request = request

        if self._on_request:
            try:
                result = self._on_request(request)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

        result = await request.wait_for_response(timeout)

        async with self._lock:
            if self._pending_request == request:
                self._pending_request = None

        return result

    def get_pending_request(self) -> ConfirmationRequest | None:
        return self._pending_request

    def approve_pending(self):
        if self._pending_request:
            self._pending_request.approve()

    def reject_pending(self):
        if self._pending_request:
            self._pending_request.reject()


_confirmation_manager: ConfirmationManager | None = None


def get_confirmation_manager() -> ConfirmationManager:
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager


def create_confirmation_manager() -> ConfirmationManager:
    global _confirmation_manager
    _confirmation_manager = ConfirmationManager()
    return _confirmation_manager
