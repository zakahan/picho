"""
Files API - HTTP Direct Implementation

Upload files to Ark Files API using direct HTTP requests.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass
class FileUploadResult:
    id: str
    status: str
    purpose: str
    filename: str | None = None
    bytes: int | None = None
    created_at: int | None = None


async def upload_file(
    file_path: str,
    api_key: str,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    purpose: str = "user_data",
    fps: float | None = None,
    timeout: float = 300.0,
) -> FileUploadResult:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    url = f"{base_url.rstrip('/')}/files"

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    with open(file_path, "rb") as f:
        files: dict[str, tuple[str, Any, str]] = {
            "file": (path.name, f, "application/octet-stream"),
        }

        data: dict[str, Any] = {
            "purpose": purpose,
        }

        if fps is not None:
            data["preprocess_configs"] = json.dumps(
                {
                    "video": {
                        "fps": fps,
                    }
                }
            )

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                files=files,
                data=data,
            )

            if response.status_code >= 400:
                error_text = response.text
                raise Exception(f"HTTP {response.status_code}: {error_text}")

            result = response.json()

    return FileUploadResult(
        id=result.get("id", ""),
        status=result.get("status", ""),
        purpose=result.get("purpose", purpose),
        filename=result.get("filename"),
        bytes=result.get("bytes"),
        created_at=result.get("created_at"),
    )


async def get_file_status(
    file_id: str,
    api_key: str,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    timeout: float = 30.0,
) -> FileUploadResult:
    url = f"{base_url.rstrip('/')}/files/{file_id}"

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)

        if response.status_code >= 400:
            error_text = response.text
            raise Exception(f"HTTP {response.status_code}: {error_text}")

        result = response.json()

    return FileUploadResult(
        id=result.get("id", ""),
        status=result.get("status", ""),
        purpose=result.get("purpose", ""),
        filename=result.get("filename"),
        bytes=result.get("bytes"),
        created_at=result.get("created_at"),
    )


async def wait_for_processing(
    file_id: str,
    api_key: str,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    poll_interval: float = 3.0,
    max_wait_seconds: float = 600.0,
    timeout: float = 30.0,
) -> FileUploadResult:
    TERMINAL_STATES = {"active", "failed"}

    start_time = asyncio.get_event_loop().time()

    while True:
        result = await get_file_status(file_id, api_key, base_url, timeout)

        if result.status in TERMINAL_STATES:
            if result.status == "failed":
                raise Exception(f"File processing failed for file_id: {file_id}")
            return result

        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed >= max_wait_seconds:
            raise TimeoutError(
                f"File processing timed out after {max_wait_seconds} seconds"
            )

        await asyncio.sleep(poll_interval)


async def upload_and_wait(
    file_path: str,
    api_key: str,
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    purpose: str = "user_data",
    fps: float | None = None,
    poll_interval: float = 3.0,
    max_wait_seconds: float = 600.0,
    upload_timeout: float = 300.0,
    status_timeout: float = 30.0,
) -> str:
    result = await upload_file(
        file_path=file_path,
        api_key=api_key,
        base_url=base_url,
        purpose=purpose,
        fps=fps,
        timeout=upload_timeout,
    )
    final_result = await wait_for_processing(
        file_id=result.id,
        api_key=api_key,
        base_url=base_url,
        poll_interval=poll_interval,
        max_wait_seconds=max_wait_seconds,
        timeout=status_timeout,
    )

    return final_result.id
