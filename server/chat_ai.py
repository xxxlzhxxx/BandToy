from __future__ import annotations

import base64
import json
import math
import os
import struct
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from emotion_ai import AsrClient, DEFAULT_ARK_BASE_URL


DEFAULT_TTS_URL = "https://openspeech.bytedance.com/api/v1/tts"
DEFAULT_TTS_V3_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_TTS_CLUSTER = "volcano_tts"
DEFAULT_TTS_VOICE_TYPE = "BV700_V2_streaming"
DEFAULT_TTS_RESOURCE_ID = "seed-tts-2.0"
DEFAULT_TTS_SPEAKER = "zh_female_vv_uranus_bigtts"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_CHAT_MODEL = "ep-20260224155825-66kc4"


@dataclass(frozen=True)
class ChatTextResult:
    text: str
    source: str = "fallback"
    raw: str = ""
    error: str = ""


@dataclass(frozen=True)
class TtsResult:
    audio: bytes
    mime_type: str
    audio_format: str
    sample_rate: int
    source: str = "fallback"
    raw: str = ""
    error: str = ""


@dataclass(frozen=True)
class ChatResponse:
    recognized: bool
    heard_text: str
    spoken_text: str
    audio: bytes
    audio_mime_type: str
    audio_format: str
    sample_rate: int
    llm_source: str
    tts_source: str
    error: str = ""


def _wav_header(sample_count: int, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    data_size = sample_count * 2
    riff_size = 36 + data_size
    return b"".join([
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16),
        b"data",
        struct.pack("<I", data_size),
    ])


def synthesize_fallback_wav(text: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    duration_ms = min(1800, max(700, 420 + len(text.encode("utf-8")) * 18))
    sample_count = int(sample_rate * duration_ms / 1000)
    samples = bytearray()
    base = 420 + (len(text) % 5) * 35
    for index in range(sample_count):
        t = index / sample_rate
        envelope = min(1.0, index / max(1, sample_rate * 0.02))
        envelope *= min(1.0, (sample_count - index) / max(1, sample_rate * 0.08))
        tone = math.sin(2 * math.pi * base * t) + 0.25 * math.sin(2 * math.pi * base * 1.5 * t)
        sample = int(max(-1.0, min(1.0, tone * envelope * 0.35)) * 32767)
        samples.extend(struct.pack("<h", sample))
    return _wav_header(sample_count, sample_rate) + bytes(samples)


def pcm16_to_wav(audio: bytes, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    return _wav_header(len(audio) // 2, sample_rate) + audio[: len(audio) - (len(audio) % 2)]


def _decode_v3_tts_audio(raw: str) -> bytes:
    chunks: list[bytes] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        code = int(data.get("code", 0))
        if code not in (0, 20000000):
            raise ValueError(str(data.get("message") or code))
        audio_b64 = data.get("data") or data.get("audio")
        if audio_b64:
            chunks.append(base64.b64decode(str(audio_b64)))
    if chunks:
        return b"".join(chunks)
    data = json.loads(raw)
    audio_b64 = data.get("data") or data.get("audio")
    return base64.b64decode(str(audio_b64)) if audio_b64 else b""


class LlmChatClient:
    def __init__(self, disabled: bool = False):
        self.disabled = disabled
        self.api_key = os.environ.get("ARK_API_KEY", "")
        self.base_url = os.environ.get("ARK_BASE_URL", DEFAULT_ARK_BASE_URL).rstrip("/")
        self.model = os.environ.get("BANDTOY_CHAT_MODEL") or os.environ.get("ARK_LLM_MODEL") or DEFAULT_CHAT_MODEL

    def reply(self, text: str) -> ChatTextResult:
        clean_text = (text or "").strip()
        if self.disabled or not self.api_key or not self.model:
            return ChatTextResult(text=self._fallback_reply(clean_text), source="fallback")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 BandToy 桌面音乐玩具里的小熊角色。"
                        "请直接用中文口语回复用户，语气温柔、短句、像玩具伙伴。"
                        "不要自称AI，不要解释技术。回复控制在35个汉字以内。"
                    ),
                },
                {"role": "user", "content": clean_text},
            ],
            "temperature": 0.5,
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
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
            reply = str(body["choices"][0]["message"]["content"]).strip()
            return ChatTextResult(text=reply or self._fallback_reply(clean_text), source="llm", raw=json.dumps(body, ensure_ascii=False))
        except (KeyError, IndexError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return ChatTextResult(text=self._fallback_reply(clean_text), source="fallback", error=str(exc))

    @staticmethod
    def _fallback_reply(text: str) -> str:
        if text:
            return f"我听见你说：{text}。我在这里陪你。"
        return "我听见啦。我在这里陪你。"


class VolcTtsClient:
    def __init__(self, disabled: bool = False):
        self.disabled = disabled
        self.app_id = os.environ.get("VOLC_TTS_APP_ID", "")
        self.access_token = os.environ.get("VOLC_TTS_ACCESS_TOKEN", "")
        self.resource_id = os.environ.get("VOLC_TTS_RESOURCE_ID", DEFAULT_TTS_RESOURCE_ID)
        self.url = os.environ.get("VOLC_TTS_URL", DEFAULT_TTS_V3_URL)
        self.cluster = os.environ.get("VOLC_TTS_CLUSTER", DEFAULT_TTS_CLUSTER)
        self.voice_type = os.environ.get("VOLC_TTS_VOICE_TYPE", DEFAULT_TTS_VOICE_TYPE)
        self.speaker = os.environ.get("VOLC_TTS_SPEAKER", DEFAULT_TTS_SPEAKER)
        self.uid = os.environ.get("VOLC_TTS_UID", "bandtoy-server")
        self.sample_rate = int(os.environ.get("VOLC_TTS_SAMPLE_RATE", str(DEFAULT_SAMPLE_RATE)))

    def synthesize(self, text: str) -> TtsResult:
        if self.disabled or not self.app_id or not self.access_token:
            return TtsResult(
                audio=synthesize_fallback_wav(text, self.sample_rate),
                mime_type="audio/wav",
                audio_format="wav",
                sample_rate=self.sample_rate,
                source="fallback",
                error="VOLC_TTS_APP_ID or VOLC_TTS_ACCESS_TOKEN is not set",
            )
        if "/api/v3/tts/" in self.url:
            return self._synthesize_v3(text)
        return self._synthesize_v1(text)

    def _synthesize_v3(self, text: str) -> TtsResult:
        payload = self._v3_payload(text)
        request = self._v3_request(payload)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
            audio = _decode_v3_tts_audio(raw)
            if not audio:
                raise ValueError("TTS v3 response did not contain audio data")
            return TtsResult(
                audio=audio,
                mime_type="application/octet-stream",
                audio_format="pcm",
                sample_rate=self.sample_rate,
                source="volc_tts_v3",
                raw=raw[:512],
            )
        except (KeyError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return TtsResult(
                audio=synthesize_fallback_wav(text, self.sample_rate),
                mime_type="audio/wav",
                audio_format="wav",
                sample_rate=self.sample_rate,
                source="fallback",
                error=str(exc),
            )

    def stream_pcm(self, text: str):
        if self.disabled or not self.app_id or not self.access_token:
            fallback = synthesize_fallback_wav(text, self.sample_rate)
            yield fallback[44:]
            return
        if "/api/v3/tts/" not in self.url:
            result = self.synthesize(text)
            if result.audio_format == "wav":
                yield result.audio[44:]
            else:
                yield result.audio
            return
        request = self._v3_request(self._v3_payload(text))
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    code = int(data.get("code", 0))
                    if code not in (0, 20000000):
                        raise ValueError(str(data.get("message") or code))
                    audio_b64 = data.get("data") or data.get("audio")
                    if audio_b64:
                        yield base64.b64decode(str(audio_b64))
        except (KeyError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            fallback = synthesize_fallback_wav(text, self.sample_rate)
            yield fallback[44:]

    def _v3_payload(self, text: str) -> dict:
        return {
            "user": {"uid": self.uid},
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": self.sample_rate,
                },
            },
        }

    def _v3_request(self, payload: dict) -> urllib.request.Request:
        return urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "X-Api-App-Id": self.app_id,
                "X-Api-Access-Key": self.access_token,
                "X-Api-Resource-Id": self.resource_id,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

    def _synthesize_v1(self, text: str) -> TtsResult:
        payload = {
            "app": {
                "appid": self.app_id,
                "token": self.access_token,
                "cluster": self.cluster,
            },
            "user": {"uid": self.uid},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": "wav",
                "rate": self.sample_rate,
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",
            },
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer;{self.access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
            if int(body.get("code", -1)) != 3000:
                raise ValueError(str(body.get("message") or body.get("code")))
            audio = base64.b64decode(str(body["data"]))
            return TtsResult(
                audio=audio,
                mime_type="audio/wav",
                audio_format="wav",
                sample_rate=self.sample_rate,
                source="volc_tts",
                raw=json.dumps({"code": body.get("code"), "reqid": body.get("reqid", "")}, ensure_ascii=False),
            )
        except (KeyError, ValueError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return TtsResult(
                audio=synthesize_fallback_wav(text, self.sample_rate),
                mime_type="audio/wav",
                audio_format="wav",
                sample_rate=self.sample_rate,
                source="fallback",
                error=str(exc),
            )


class ChatAi:
    def __init__(
        self,
        asr_client: AsrClient | None = None,
        llm_client: LlmChatClient | None = None,
        tts_client: VolcTtsClient | None = None,
    ):
        self.asr_client = asr_client or AsrClient()
        self.llm_client = llm_client or LlmChatClient()
        self.tts_client = tts_client or VolcTtsClient()

    def reply_text(self, text: str) -> ChatResponse:
        llm = self.llm_client.reply(text)
        tts = self.tts_client.synthesize(llm.text)
        return ChatResponse(
            recognized=True,
            heard_text=text,
            spoken_text=llm.text,
            audio=tts.audio,
            audio_mime_type=tts.mime_type,
            audio_format=tts.audio_format,
            sample_rate=tts.sample_rate,
            llm_source=llm.source,
            tts_source=tts.source,
            error=llm.error or tts.error,
        )

    def reply_audio(self, audio: bytes, content_type: str) -> ChatResponse:
        asr = self.asr_client.transcribe(audio, content_type)
        if not asr.ok:
            fallback = "我刚刚没有听清，可以再靠近一点说吗？"
            tts = self.tts_client.synthesize(fallback)
            return ChatResponse(
                recognized=False,
                heard_text="",
                spoken_text=fallback,
                audio=tts.audio,
                audio_mime_type=tts.mime_type,
                audio_format=tts.audio_format,
                sample_rate=tts.sample_rate,
                llm_source="asr_error",
                tts_source=tts.source,
                error=asr.error,
            )
        return self.reply_text(asr.text)
