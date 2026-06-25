from __future__ import annotations

import json
import os
import re
import base64
import gzip
import hashlib
import secrets
import socket
import ssl
import struct
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from music_personality import Emotion, EmotionRouter


DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_VOLC_ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"
DEFAULT_VOLC_ASR_RESOURCE_ID = "volc.seedasr.sauc.duration"


@dataclass(frozen=True)
class EmotionResult:
    emotion: Emotion
    text: str = ""
    energy: float | None = None
    intent: str = ""
    source: str = "fallback"
    raw: str = ""
    error: str = ""


@dataclass(frozen=True)
class AsrResult:
    ok: bool
    text: str = ""
    raw: dict[str, Any] | None = None
    error: str = ""
    log_id: str = ""


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(0))


def _normalize_emotion(value: str, fallback_text: str = "") -> Emotion:
    normalized = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "happy": Emotion.HAPPY,
        "joy": Emotion.HAPPY,
        "sad": Emotion.SAD,
        "comfort": Emotion.COMFORT,
        "tired": Emotion.COMFORT,
        "sleep": Emotion.SLEEP,
        "sleepy": Emotion.SLEEP,
        "curious": Emotion.CURIOUS,
        "question": Emotion.CURIOUS,
        "greeting": Emotion.GREETING,
        "hello": Emotion.GREETING,
        "thinking": Emotion.THINKING,
        "unknown": Emotion.THINKING,
    }
    return aliases.get(normalized) or EmotionRouter().parse_input(fallback_text or value)


def parse_llm_emotion(text: str, source_text: str = "") -> EmotionResult:
    try:
        data = _json_object_from_text(text)
    except (json.JSONDecodeError, TypeError):
        data = None
    if data:
        emotion = _normalize_emotion(str(data.get("emotion", "")), source_text)
        energy_value = data.get("energy")
        try:
            energy = None if energy_value is None else max(0.0, min(1.0, float(energy_value)))
        except (TypeError, ValueError):
            energy = None
        return EmotionResult(
            emotion=emotion,
            text=source_text,
            energy=energy,
            intent=str(data.get("intent", "")),
            source="llm",
            raw=text,
        )
    return EmotionResult(
        emotion=EmotionRouter().parse_input(source_text or text),
        text=source_text,
        source="fallback",
        raw=text,
    )


class LlmEmotionClient:
    def __init__(self, disabled: bool = False):
        self.disabled = disabled
        self.api_key = os.environ.get("ARK_API_KEY", "")
        self.base_url = os.environ.get("ARK_BASE_URL", DEFAULT_ARK_BASE_URL).rstrip("/")
        self.model = os.environ.get("BANDTOY_LLM_MODEL") or os.environ.get("ARK_LLM_MODEL", "")

    def classify(self, text: str) -> EmotionResult:
        if self.disabled or not self.api_key or not self.model:
            return EmotionResult(emotion=EmotionRouter().parse_input(text), text=text, source="fallback")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify the user's emotional tone for a toy that only replies with music. "
                        "Return only compact JSON with keys: emotion, energy, intent. "
                        "emotion must be one of happy, sad, comfort, sleep, curious, greeting, thinking. "
                        "energy is a number from 0 to 1."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = json.loads(response.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            result = parse_llm_emotion(content, source_text=text)
            return EmotionResult(
                emotion=result.emotion,
                text=text,
                energy=result.energy,
                intent=result.intent,
                source=result.source,
                raw=result.raw,
            )
        except (KeyError, IndexError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            fallback = EmotionRouter().parse_input(text)
            return EmotionResult(emotion=fallback, text=text, source="fallback", error=str(exc))


class AsrClient:
    def __init__(self):
        self.app_id = os.environ.get("VOLC_ASR_APP_ID", "")
        self.access_token = os.environ.get("VOLC_ASR_ACCESS_TOKEN", "")
        self.secret_key = os.environ.get("VOLC_ASR_SECRET_KEY", "")
        self.url = os.environ.get("VOLC_ASR_URL", DEFAULT_VOLC_ASR_URL)
        self.resource_id = os.environ.get("VOLC_ASR_RESOURCE_ID", DEFAULT_VOLC_ASR_RESOURCE_ID)
        self.language = os.environ.get("VOLC_ASR_LANGUAGE", "zh-CN")
        self.uid = os.environ.get("VOLC_ASR_UID", "bandtoy-server")

    def transcribe(self, audio: bytes, content_type: str) -> AsrResult:
        if not self.app_id or not self.access_token:
            return AsrResult(ok=False, error="VOLC_ASR_APP_ID or VOLC_ASR_ACCESS_TOKEN is not set")
        audio_format = _audio_format_from_content_type(content_type, audio)
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }
        protocol = VolcAsrProtocol()
        first_frame = protocol.build_full_client_request(
            audio_format=audio_format,
            language=self.language,
            uid=self.uid,
        )
        audio_frame = protocol.build_audio_request(audio, is_last=True)
        try:
            with SimpleWebSocketClient(self.url, headers, timeout=45) as websocket:
                websocket.send_binary(first_frame)
                websocket.recv_binary()
                websocket.send_binary(audio_frame)
                body = protocol.recv_json_response(websocket)
                log_id = websocket.response_headers.get("x-tt-logid", "")
        except (OSError, ValueError, TimeoutError, json.JSONDecodeError) as exc:
            return AsrResult(ok=False, error=str(exc))
        text = _extract_asr_text(body)
        return AsrResult(
            ok=bool(text),
            text=text,
            raw=body,
            error="" if text else "ASR response did not contain text",
            log_id=log_id,
        )


class VolcAsrProtocol:
    VERSION_AND_HEADER = 0x11
    SERIALIZATION_JSON_GZIP = 0x11
    SERIALIZATION_NONE_GZIP = 0x01

    @classmethod
    def build_full_client_request(cls, audio_format: str, language: str, uid: str) -> bytes:
        payload = {
            "user": {"uid": uid},
            "audio": {
                "format": audio_format,
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "language": language,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": False,
                "show_utterances": True,
                "enable_emotion_detection": True,
                "result_type": "full",
            },
        }
        body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        header = bytes([
            cls.VERSION_AND_HEADER,
            0x10,  # full client request, no sequence.
            cls.SERIALIZATION_JSON_GZIP,
            0x00,
        ])
        return header + len(body).to_bytes(4, "big") + body

    @classmethod
    def build_audio_request(cls, audio: bytes, is_last: bool) -> bytes:
        body = gzip.compress(audio)
        flags = 0x02 if is_last else 0x00
        header = bytes([
            cls.VERSION_AND_HEADER,
            (0x02 << 4) | flags,
            cls.SERIALIZATION_NONE_GZIP,
            0x00,
        ])
        return header + len(body).to_bytes(4, "big") + body

    def recv_json_response(self, websocket: "SimpleWebSocketClient") -> dict[str, Any]:
        last_body: dict[str, Any] = {}
        for _ in range(6):
            packet = websocket.recv_binary()
            parsed = self.parse_server_packet(packet)
            if parsed.get("message_type") == 0x0F:
                raise ValueError(f"Volc ASR error {parsed.get('code')}: {parsed.get('error')}")
            body = parsed.get("body")
            if isinstance(body, dict):
                last_body = body
                if _extract_asr_text(body) or (parsed.get("flags") == 0x03):
                    return body
        return last_body

    @staticmethod
    def parse_server_packet(packet: bytes) -> dict[str, Any]:
        if len(packet) < 8:
            raise ValueError("ASR response packet is too short")
        header_size = (packet[0] & 0x0F) * 4
        message_type = packet[1] >> 4
        flags = packet[1] & 0x0F
        compression = packet[2] & 0x0F
        offset = header_size
        sequence = None
        if flags in (0x01, 0x03):
            sequence = int.from_bytes(packet[offset:offset + 4], "big", signed=True)
            offset += 4
        if message_type == 0x0F:
            code = int.from_bytes(packet[offset:offset + 4], "big")
            offset += 4
            size = int.from_bytes(packet[offset:offset + 4], "big")
            offset += 4
            error = packet[offset:offset + size].decode("utf-8", errors="replace")
            return {"message_type": message_type, "flags": flags, "code": code, "error": error}
        size = int.from_bytes(packet[offset:offset + 4], "big")
        offset += 4
        payload = packet[offset:offset + size]
        if compression == 0x01:
            payload = gzip.decompress(payload)
        body = json.loads(payload.decode("utf-8")) if payload else {}
        return {"message_type": message_type, "flags": flags, "sequence": sequence, "body": body}


class SimpleWebSocketClient:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, url: str, headers: dict[str, str], timeout: float = 45.0):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.response_headers: dict[str, str] = {}

    def __enter__(self) -> "SimpleWebSocketClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in ("ws", "wss"):
            raise ValueError(f"ASR URL must be ws/wss, got {parsed.scheme or 'empty'}")
        host = parsed.hostname
        if not host:
            raise ValueError("ASR URL host is empty")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        raw_sock.settimeout(self.timeout)
        if parsed.scheme == "wss":
            self.sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request_headers = {
            "Host": host if parsed.port is None else f"{host}:{port}",
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Sec-WebSocket-Key": key,
            "Sec-WebSocket-Version": "13",
            **self.headers,
        }
        request = "\r\n".join([f"GET {path} HTTP/1.1", *[f"{k}: {v}" for k, v in request_headers.items()], "", ""])
        self._send_all(request.encode("utf-8"))
        status, headers = self._read_handshake_response()
        if " 101 " not in status:
            raise ValueError(f"WebSocket upgrade failed: {status}")
        accept = headers.get("sec-websocket-accept", "")
        expected = base64.b64encode(hashlib.sha1((key + self.GUID).encode("ascii")).digest()).decode("ascii")
        if accept and accept != expected:
            raise ValueError("WebSocket accept key mismatch")
        self.response_headers = headers

    def send_binary(self, payload: bytes) -> None:
        if self.sock is None:
            raise ValueError("WebSocket is not connected")
        header = bytearray([0x82])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._send_all(bytes(header) + mask + masked)

    def recv_binary(self) -> bytes:
        while True:
            frame = self._recv_frame()
            opcode = frame["opcode"]
            if opcode == 0x02:
                return frame["payload"]
            if opcode == 0x08:
                raise ValueError("WebSocket closed by server")
            if opcode == 0x09:
                self._send_pong(frame["payload"])

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _send_pong(self, payload: bytes) -> None:
        self._send_all(bytes([0x8A, len(payload)]) + payload)

    def _recv_frame(self) -> dict[str, Any]:
        first = self._recv_exact(2)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return {"opcode": opcode, "payload": payload}

    def _read_handshake_response(self) -> tuple[str, dict[str, str]]:
        raw = bytearray()
        while b"\r\n\r\n" not in raw:
            chunk = self._recv_exact(1)
            raw.extend(chunk)
            if len(raw) > 65536:
                raise ValueError("WebSocket handshake response is too large")
        lines = raw.decode("iso-8859-1").split("\r\n")
        status = lines[0]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        return status, headers

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise ValueError("WebSocket is not connected")
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                raise ValueError("WebSocket connection closed unexpectedly")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_all(self, data: bytes) -> None:
        if self.sock is None:
            raise ValueError("WebSocket is not connected")
        self.sock.sendall(data)


def _extract_asr_text(body: dict[str, Any]) -> str:
    candidates = [
        body.get("text"),
        body.get("result", {}).get("text") if isinstance(body.get("result"), dict) else None,
        body.get("utterances", [{}])[0].get("text") if isinstance(body.get("utterances"), list) and body.get("utterances") else None,
    ]
    result = body.get("result")
    if isinstance(result, list) and result and isinstance(result[0], dict):
        candidates.append(result[0].get("text"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _audio_format_from_content_type(content_type: str, audio: bytes) -> str:
    normalized = (content_type or "").lower()
    if "wav" in normalized or audio.startswith(b"RIFF"):
        return "wav"
    if "mpeg" in normalized or "mp3" in normalized:
        return "mp3"
    if "ogg" in normalized:
        return "ogg"
    return "pcm"


class EmotionAi:
    def __init__(self, llm_client: LlmEmotionClient | None = None, asr_client: AsrClient | None = None):
        self.llm_client = llm_client or LlmEmotionClient()
        self.asr_client = asr_client or AsrClient()

    def classify_text(self, text: str) -> EmotionResult:
        return self.llm_client.classify(text)

    def classify_audio(self, audio: bytes, content_type: str) -> EmotionResult:
        asr = self.asr_client.transcribe(audio, content_type)
        if not asr.ok:
            raw = json.dumps({"asr_raw": asr.raw, "asr_log_id": asr.log_id}, ensure_ascii=False)
            return EmotionResult(emotion=Emotion.THINKING, source="asr_error", raw=raw, error=asr.error)
        result = self.llm_client.classify(asr.text)
        return EmotionResult(
            emotion=result.emotion,
            text=asr.text,
            energy=result.energy,
            intent=result.intent,
            source=result.source,
            raw=result.raw,
            error=result.error,
        )
