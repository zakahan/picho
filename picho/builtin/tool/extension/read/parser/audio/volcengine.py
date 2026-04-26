"""
Volcengine audio ASR provider.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from picho.builtin.tool.extension.read.parser.parser_audio import (
    AudioTranscript,
    AudioUtterance,
)
from picho.config import ReadAudioAsrConfig, ReadVolcengineAsrConfig


SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
RESOURCE_ID = "volc.seedasr.auc"
SEQ = "-1"

STATUS_SUCCESS = "20000000"
STATUS_PROCESSING = "20000001"
STATUS_IN_QUEUE = "20000002"
STATUS_NO_VOICE = "20000003"


class VolcengineTosUploader:
    def __init__(
        self,
        *,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ):
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.region = region
        self.endpoint = f"https://{bucket}.tos-{region}.volces.com"

    def upload(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        self._ensure_bucket_exists()
        content = path.read_bytes()
        payload_hash = hashlib.sha256(content).hexdigest()
        object_key = self._build_object_key(path)
        amz_date, date_header = self._date_headers()
        headers = {
            "Host": f"{self.bucket}.tos-{self.region}.volces.com",
            "x-tos-content-sha256": payload_hash,
            "x-tos-acl": "public-read",
            "Content-Type": self._guess_content_type(path.suffix),
            "Date": date_header,
            "x-tos-date": amz_date,
        }
        headers["Authorization"] = self._sign(
            "PUT", f"/{object_key}", headers, payload_hash
        )
        headers["Content-Length"] = str(len(content))

        url = f"{self.endpoint}/{object_key}"
        with httpx.Client(timeout=60) as client:
            response = client.put(url, headers=headers, content=content)
            response.raise_for_status()
        return url

    def _ensure_bucket_exists(self) -> None:
        payload_hash = hashlib.sha256(b"").hexdigest()
        amz_date, date_header = self._date_headers()
        headers = {
            "Host": f"{self.bucket}.tos-{self.region}.volces.com",
            "x-tos-content-sha256": payload_hash,
            "Date": date_header,
            "x-tos-date": amz_date,
        }
        headers["Authorization"] = self._sign("HEAD", "/", headers, payload_hash)
        with httpx.Client(timeout=60) as client:
            response = client.head(self.endpoint, headers=headers)
            if response.status_code == 200:
                return
            if response.status_code != 404:
                response.raise_for_status()

            create_headers = dict(headers)
            create_headers["Authorization"] = self._sign(
                "PUT", "/", create_headers, payload_hash
            )
            create_response = client.put(self.endpoint, headers=create_headers)
            create_response.raise_for_status()

    def _sign(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        payload_hash: str,
    ) -> str:
        t = datetime.now(timezone.utc)
        date_stamp = t.strftime("%Y%m%d")
        amz_date = t.strftime("%Y%m%dT%H%M%SZ")
        signed_headers = {
            k.lower(): v
            for k, v in headers.items()
            if k.lower() == "content-type"
            or k.lower() == "host"
            or k.lower().startswith("x-tos-")
        }
        canonical_headers = "".join(
            f"{k}:{v}\n" for k, v in sorted(signed_headers.items())
        )
        signed_header_keys = ";".join(sorted(signed_headers.keys()))
        canonical_request = (
            f"{method}\n{path}\n\n{canonical_headers}\n"
            f"{signed_header_keys}\n{payload_hash}"
        )
        credential_scope = f"{date_stamp}/{self.region}/tos/request"
        hashed_canonical = hashlib.sha256(canonical_request.encode()).hexdigest()
        string_to_sign = (
            f"TOS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n{hashed_canonical}"
        )
        k_date = self._hmac_sha256(self.secret_key.encode(), date_stamp.encode())
        k_region = self._hmac_sha256(k_date, self.region.encode())
        k_service = self._hmac_sha256(k_region, b"tos")
        k_signing = self._hmac_sha256(k_service, b"request")
        signature = hmac.new(
            k_signing, string_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        credential = f"{self.access_key}/{credential_scope}"
        return (
            "TOS4-HMAC-SHA256 "
            f"Credential={credential}, "
            f"SignedHeaders={signed_header_keys}, "
            f"Signature={signature}"
        )

    @staticmethod
    def _hmac_sha256(key: bytes, data: bytes) -> bytes:
        return hmac.new(key, data, hashlib.sha256).digest()

    @staticmethod
    def _date_headers() -> tuple[str, str]:
        t = datetime.now(timezone.utc)
        return (
            t.strftime("%Y%m%dT%H%M%SZ"),
            t.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        )

    @staticmethod
    def _build_object_key(path: Path) -> str:
        date_prefix = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"uploads/{date_prefix}/{uuid.uuid4().hex}{path.suffix.lower()}"

    @staticmethod
    def _guess_content_type(suffix: str) -> str:
        if suffix.lower() == ".mp3":
            return "audio/mpeg"
        if suffix.lower() == ".wav":
            return "audio/wav"
        return "application/octet-stream"


class VolcengineAudioAsrProvider:
    name = "volcengine"

    def transcribe(self, file_path: str, config: ReadAudioAsrConfig) -> AudioTranscript:
        volc_config = config.volcengine
        uploader = self._build_uploader(volc_config)
        audio_url = uploader.upload(file_path)
        result = self._transcribe_url(audio_url, file_path, config)
        return self._build_transcript(result)

    def _build_uploader(self, config: ReadVolcengineAsrConfig) -> VolcengineTosUploader:
        access_key = _require_env(config.tos_access_key_env)
        secret_key = _require_env(config.tos_secret_key_env)
        bucket = config.tos_bucket or _require_env(config.tos_bucket_env)
        return VolcengineTosUploader(
            access_key=access_key,
            secret_key=secret_key,
            bucket=bucket,
            region=config.tos_region,
        )

    def _transcribe_url(
        self,
        url: str,
        file_path: str,
        config: ReadAudioAsrConfig,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        headers = self._build_headers(task_id, config.volcengine.speech_api_key_env)
        audio_format = Path(file_path).suffix.lower().lstrip(".")
        body: dict[str, Any] = {
            "user": {"uid": "picho"},
            "audio": {
                "url": url,
                "format": audio_format,
                "codec": config.volcengine.codec,
                "rate": config.volcengine.sample_rate,
                "bits": 16,
                "channel": config.volcengine.channel,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": config.enable_itn,
                "enable_punc": config.enable_punc,
                "enable_ddc": config.enable_ddc,
                "enable_speaker_info": config.enable_speaker_info,
                "show_utterances": config.include_utterances,
                "vad_segment": config.vad_segment,
            },
        }
        if config.language:
            body["audio"]["language"] = config.language

        with httpx.Client(timeout=30) as client:
            response = client.post(SUBMIT_URL, headers=headers, json=body)
            status_code = response.headers.get("X-Api-Status-Code", "")
            message = response.headers.get("X-Api-Message", "")
            if status_code and status_code != STATUS_SUCCESS:
                raise RuntimeError(
                    f"Submit failed: status={status_code}, message={message}"
                )

            deadline = time.monotonic() + config.timeout_seconds
            while time.monotonic() < deadline:
                time.sleep(config.poll_interval_seconds)
                query_response = client.post(
                    QUERY_URL,
                    headers=self._build_headers(
                        task_id, config.volcengine.speech_api_key_env
                    ),
                    content=b"{}",
                )
                query_status = query_response.headers.get("X-Api-Status-Code", "")
                query_message = query_response.headers.get("X-Api-Message", "")
                if query_status == STATUS_SUCCESS:
                    data = query_response.json() if query_response.content else {}
                    return {"status": "success", "task_id": task_id, "data": data}
                if query_status == STATUS_NO_VOICE:
                    raise RuntimeError("No voice detected in audio")
                if query_status and query_status not in {
                    STATUS_PROCESSING,
                    STATUS_IN_QUEUE,
                }:
                    raise RuntimeError(
                        f"Query failed: status={query_status}, message={query_message}"
                    )

        raise TimeoutError(
            f"ASR task {task_id} still processing after {config.timeout_seconds}s"
        )

    @staticmethod
    def _build_headers(task_id: str, api_key_env: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Api-Key": _require_env(api_key_env),
            "X-Api-Resource-Id": RESOURCE_ID,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": SEQ,
        }

    @staticmethod
    def _build_transcript(result: dict[str, Any]) -> AudioTranscript:
        data = result.get("data", {})
        result_info = data.get("result", {})
        audio_info = data.get("audio_info", {})
        utterances = [
            AudioUtterance(
                text=item.get("text", ""),
                start_time=item.get("start_time"),
                end_time=item.get("end_time"),
                raw=item,
            )
            for item in result_info.get("utterances", [])
        ]
        return AudioTranscript(
            provider="volcengine",
            text=result_info.get("text", ""),
            duration=audio_info.get("duration"),
            task_id=result.get("task_id"),
            utterances=utterances,
        )


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise PermissionError(f"{name} environment variable is not set")
    return value
