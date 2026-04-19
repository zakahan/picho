from fastapi import FastAPI
import uvicorn

from ..runner import Runner
from .composition import (
    APIAppBuilder,
    CoreRoutesBundle,
    SessionAPIAdapter,
    SessionRouteBundle,
)
from .schemas import CreateSessionRequest, RequestMessage, RunRequest


class APIServer:
    def __init__(
        self,
        runner: Runner,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.runner = runner
        self.host = host
        self.port = port
        self.session_adapter = SessionAPIAdapter()
        self.session_routes = SessionRouteBundle(
            runner=self.runner,
            adapter=self.session_adapter,
            create_session_request_model=CreateSessionRequest,
            request_message_model=RequestMessage,
            run_request_model=RunRequest,
        )
        self.app = self._create_app()

    def _create_app(self) -> FastAPI:
        builder = APIAppBuilder(title="picho API")
        builder.add_bundle(CoreRoutesBundle())
        builder.add_bundle(self.session_routes)
        return builder.build()

    def run(self):
        uvicorn.run(self.app, host=self.host, port=self.port)
