# picho API Server

picho API Server is a FastAPI-based web server that exposes Agent through REST API endpoints, supporting session management and streaming dialogue capabilities.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Product Service                          │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ Custom Routes   │  │ Custom Adapter  │  │ Custom Models   │ │
│  │ /projects       │  │ SandboxSession  │  │ ProjectRequest  │ │
│  │ /tasks          │  │ APIAdapter      │  │ AssetRequest    │ │
│  │ /assets         │  │                 │  │                 │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
│           │                   │                   │             │
└───────────┼───────────────────┼───────────────────┼─────────────┘
            │                   │                   │
            ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      APIAppBuilder                              │
│                   (Assembly Helper)                             │
├─────────────────────────────────────────────────────────────────┤
│  .add_bundle(CoreRoutesBundle)                                  │
│  .add_bundle(SessionRouteBundle)                                │
│  .build() → FastAPI App                                         │
└─────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Route Bundles                              │
├──────────────────────────┬──────────────────────────────────────┤
│   CoreRoutesBundle       │      SessionRouteBundle              │
│   ─────────────────      │      ──────────────────              │
│   GET /health            │      POST /sessions                  │
│                          │      GET /sessions/{id}              │
│                          │      GET /sessions                   │
│                          │      DELETE /sessions/{id}           │
│                          │      POST /run_sse                   │
└──────────────────────────┴──────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    SessionAPIAdapter                            │
│                   (Extension Point)                             │
├─────────────────────────────────────────────────────────────────┤
│  Lifecycle Hooks:                                               │
│  • validate_run_request() - Pre-request validation              │
│  • on_run_start() - Initialize run state                        │
│  • convert_message() - Transform request to Message             │
│  • serialize_event() - Format SSE events                        │
│  • on_run_complete() - Handle successful completion             │
│  • on_run_error() - Handle errors                               │
│  • on_run_cancelled() - Handle cancellation                     │
└─────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Runner                                  │
│                    (Agent Execution)                            │
└─────────────────────────────────────────────────────────────────┘
```

## Core Concepts

### Composition Over Inheritance

The API layer uses a composition-oriented architecture. Instead of inheriting from a monolithic server class, product services compose reusable building blocks:

- **Route Bundles**: Reusable sets of API endpoints
- **Adapters**: Customizable behavior hooks for request processing
- **Builder**: Assembly helper for constructing the FastAPI app

### Core Components

#### `APIAppBuilder`

A fluent builder for constructing FastAPI applications:

```python
from picho.api.composition import APIAppBuilder, CoreRoutesBundle, SessionRouteBundle
from picho.api.schemas import CreateSessionRequest, RequestMessage, RunRequest

app = (APIAppBuilder(title="My Agent API")
       .add_bundle(CoreRoutesBundle())
       .add_bundle(SessionRouteBundle(
    runner=runner,
    adapter=adapter,
    create_session_request_model=CreateSessionRequest,
    request_message_model=RequestMessage,
    run_request_model=RunRequest,
))
       .build())
```

#### `CoreRoutesBundle`

Provides the most generic core routes:

- `GET /health` - Health check endpoint

#### `SessionRouteBundle`

Provides reusable session and SSE endpoints:

- `POST /sessions` - Create a new session
- `GET /sessions/{session_id}` - Get session by ID
- `GET /sessions` - List all sessions
- `DELETE /sessions/{session_id}` - Delete a session
- `POST /sessions/{session_id}/abort` - Abort the active run in a session
- `POST /sessions/{session_id}/steer` - Queue a steering message for a session
- `POST /run_sse` - Execute agent with SSE streaming

#### `SessionAPIAdapter`

The primary extension point for customizing behavior:

| Method | Purpose |
|--------|---------|
| `validate_run_request()` | Validate incoming requests before execution |
| `on_run_start()` | Initialize state before agent execution |
| `convert_message()` | Transform request messages to internal `Message` format |
| `serialize_event()` | Format agent events for SSE output |
| `on_run_complete()` | Handle successful execution completion |
| `on_run_error()` | Handle execution errors |
| `on_run_cancelled()` | Handle execution cancellation |

### Request Flow

```
HTTP Request
    │
    ▼
SessionRouteBundle
    │
    ▼
SessionAPIAdapter.validate_run_request()
    │
    ▼
SessionAPIAdapter.on_run_start()
    │
    ▼
SessionAPIAdapter.convert_message()
    │
    ▼
Runner.prompt()
    │
    ▼
SSE Event Loop
    │
    ▼
SessionAPIAdapter.serialize_event()
    │
    ▼
SessionAPIAdapter.on_run_complete() / on_run_error()
    │
    ▼
HTTP SSE Response
```

## Usage

### Default Server (Simple Cases)

For basic use cases, use the default `APIServer`:

```python
import os

from picho.api.server import APIServer
from picho.runner import Runner

config_path = os.path.join(os.getcwd(), ".picho", "config.json")

runner = Runner(config_type="json", config=config_path)
server = APIServer(runner, host="0.0.0.0", port=8000)
server.run()
```

### Custom Adapter (Product Services)

For product services that need custom behavior:

```python
from picho.api.composition import (
    APIAppBuilder,
    CoreRoutesBundle,
    SessionRouteBundle,
    SessionAPIAdapter
)
from picho.api.schemas import CreateSessionRequest, RequestMessage, RunRequest
from picho.provider.types import UserMessage, TextContent


class MySessionAPIAdapter(SessionAPIAdapter):
    async def validate_run_request(self, req):
        # Custom validation logic
        pass

    async def on_run_start(self, req):
        # Custom initialization
        return run_state, initial_messages

    async def convert_message(self, req_message, req=None):
        # Custom message conversion
        return UserMessage(content=[TextContent(type="text", text=req_message.content)])


# Build the app
app = (APIAppBuilder(title="My Product API")
       .add_bundle(CoreRoutesBundle())
       .add_bundle(SessionRouteBundle(
    runner=my_runner,
    adapter=MySessionAPIAdapter(),
    create_session_request_model=MyCreateSessionRequest,
    request_message_model=RequestMessage,
    run_request_model=MyRunRequest
))
       .build())


# Add custom routes
@app.post("/custom")
async def custom_endpoint():
    pass
```

## Design Principles

1. **Framework provides building blocks** - Reusable route bundles and adapters
2. **Products compose and extend** - Assemble what's needed, customize where necessary
3. **No deep inheritance** - Composition over inheritance for flexibility
4. **Clear separation** - Framework logic vs product-specific logic

## Core Features

- **Minimal Design**: Only `session_id` is required
- **SSE Streaming**: Real-time events via `/run_sse` endpoint
- **Multi-modal Support**: Text and image inputs
- **Production Ready**: Built-in error handling, no complex configuration

## Quick Start

### Installation

```bash
uv sync
```

### Basic Usage

```python
import os
from picho.runner import Runner
from picho.api.server import APIServer

config_path = os.path.join(os.getcwd(), ".picho", "config.json")
runner = Runner(config_type="json", config=config_path)

server = APIServer(runner)
server.run()
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/sessions` | POST | Create session |
| `/sessions/{id}` | GET | Get session |
| `/sessions` | GET | List sessions |
| `/sessions/{id}` | DELETE | Delete session |
| `/sessions/{id}/abort` | POST | Abort the active run |
| `/sessions/{id}/steer` | POST | Queue a steering message |
| `/run_sse` | POST | Execute agent (SSE streaming) |

### Example: Send a Message

```python
import httpx

# Create session
response = httpx.post("http://localhost:8000/sessions")
session_id = response.json()["session_id"]

# Send message via SSE
with httpx.stream("POST", "http://localhost:8000/run_sse", json={
    "session_id": session_id,
    "message": {"role": "user", "content": "Hello!"}
}) as response:
    for line in response.iter_lines():
        if line.startswith("data: "):
            print(line[6:])
```
