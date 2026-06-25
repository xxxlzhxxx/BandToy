#!/usr/bin/env python3
"""Character animation pipeline service for BandToy.

This module is intentionally small and dependency-light. It wraps Ark's
Seedance async video task API and keeps local job metadata so BandToy can
generate state animations such as listening, playing, and waiting.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


ARK_BASE_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
SEEDANCE_MODEL = os.environ.get("BANDTOY_SEEDANCE_MODEL", "ep-20260302192238-nhf72")
PIPELINE_ROOT = Path(__file__).resolve().parent / "pipeline_data"
JOBS_DIR = PIPELINE_ROOT / "jobs"
ASSETS_DIR = PIPELINE_ROOT / "assets"
LOCAL_ASSET_PREFIX = "/pipeline/assets/"

DEFAULT_STATES = {
    "waiting": {
        "label": "等待",
        "prompt": "The character is calmly waiting on a small wooden desk, subtle breathing motion, gentle blinking, warm handcrafted toy feeling, soft ambient light, no text.",
    },
    "listening": {
        "label": "聆听",
        "prompt": "The character leans forward slightly as if listening carefully to music, curious expression, tiny reactive body movement, soft magical music-box atmosphere, no text.",
    },
    "playing": {
        "label": "演奏",
        "prompt": "The character joyfully performs music, small rhythmic movements, charming toy-like motion, warm stage-like desk lighting, whimsical and healing mood, no text.",
    },
}

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "expired"}


def json_response(value: dict[str, Any], status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(value, ensure_ascii=False).encode("utf-8")


def read_json_body(handler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def slugify(value: str, fallback: str = "character") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or fallback


def now_ms() -> int:
    return int(time.time() * 1000)


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def local_file_to_data_url(path: str) -> str:
    file_path = Path(path).expanduser().resolve()
    data = file_path.read_bytes()
    mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def build_reference_image_item(body: dict[str, Any]) -> dict[str, Any] | None:
    image_url = body.get("reference_image_url")
    if not image_url and body.get("reference_image_path"):
        image_url = local_file_to_data_url(body["reference_image_path"])
    if not image_url:
        return None
    return {
        "type": "image_url",
        "image_url": {"url": image_url},
        "role": body.get("reference_image_role", "reference_image"),
    }


def build_state_prompt(character: dict[str, Any], state_id: str, state: dict[str, Any]) -> str:
    character_name = character.get("name", "BandToy character")
    character_description = character.get("description", "")
    visual_style = character.get(
        "visual_style",
        "miniature emotional companion toy, handcrafted, music-box inspired, soft magical realism, warm nostalgic healing mood",
    )
    state_prompt = state.get("prompt") or DEFAULT_STATES.get(state_id, {}).get("prompt", "")
    return (
        f"Keep the same character identity and visual details across clips. "
        f"Character name: {character_name}. "
        f"Character description: {character_description}. "
        f"Visual style: {visual_style}. "
        f"State animation: {state.get('label', state_id)}. {state_prompt} "
        f"Short seamless animation loop, centered full-body toy character, stable face and costume, "
        f"no subtitles, no UI, no watermark, no extra characters."
    )


def ark_headers() -> dict[str, str]:
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key:
        raise RuntimeError("ARK_API_KEY is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }


def ark_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{ARK_BASE_URL}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=ark_headers(), method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ark HTTP {exc.code}: {detail}") from exc
    return json.loads(raw.decode("utf-8"))


def create_seedance_task(payload: dict[str, Any]) -> dict[str, Any]:
    return ark_request("POST", "/contents/generations/tasks", payload)


def get_seedance_task(task_id: str) -> dict[str, Any]:
    return ark_request("GET", f"/contents/generations/tasks/{urllib.parse.quote(task_id)}")


def download_url(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "BandToyPipeline/0.1"})
    with urllib.request.urlopen(request, timeout=180) as response:
        out_path.write_bytes(response.read())


def job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def save_job(job: dict[str, Any]) -> None:
    ensure_dirs()
    job_path(job["job_id"]).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(job_id: str) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def list_jobs() -> list[dict[str, Any]]:
    ensure_dirs()
    jobs = []
    for path in sorted(JOBS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        job = json.loads(path.read_text(encoding="utf-8"))
        jobs.append({
            "job_id": job.get("job_id"),
            "character_id": job.get("character", {}).get("id"),
            "character_name": job.get("character", {}).get("name"),
            "status": job.get("status"),
            "created_at_ms": job.get("created_at_ms"),
            "updated_at_ms": job.get("updated_at_ms"),
            "state_count": len(job.get("states", {})),
        })
    return jobs


def create_animation_pipeline(body: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    character = body.get("character") or {}
    character_name = character.get("name") or body.get("character_name") or "BandToy Character"
    character_id = slugify(character.get("id") or character_name)
    character = {
        "id": character_id,
        "name": character_name,
        "description": character.get("description") or body.get("character_description", ""),
        "visual_style": character.get("visual_style") or body.get("visual_style", ""),
    }

    requested_states = body.get("states") or DEFAULT_STATES
    if isinstance(requested_states, list):
        states = {
            slugify(item.get("id") or item.get("label") or str(index), f"state-{index}"): item
            for index, item in enumerate(requested_states)
        }
    else:
        states = requested_states

    reference_item = build_reference_image_item(body)
    model = body.get("model") or SEEDANCE_MODEL
    ratio = body.get("ratio", "1:1")
    duration = int(body.get("duration", 4))
    resolution = body.get("resolution", "720p")
    generate_audio = bool(body.get("generate_audio", False))
    watermark = bool(body.get("watermark", False))
    return_last_frame = bool(body.get("return_last_frame", True))
    seed = int(body.get("seed", -1))

    job_id = f"anim-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    job = {
        "job_id": job_id,
        "type": "character_state_animations",
        "status": "submitted",
        "character": character,
        "created_at_ms": now_ms(),
        "updated_at_ms": now_ms(),
        "model": model,
        "ratio": ratio,
        "duration": duration,
        "resolution": resolution,
        "states": {},
    }

    for state_id, state_value in states.items():
        state = state_value if isinstance(state_value, dict) else {"label": str(state_value)}
        prompt = build_state_prompt(character, state_id, state)
        content = [{"type": "text", "text": prompt}]
        if reference_item:
            content.append(reference_item)
        task_payload = {
            "model": model,
            "content": content,
            "ratio": ratio,
            "duration": duration,
            "resolution": resolution,
            "watermark": watermark,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
        }
        if seed >= 0:
            task_payload["seed"] = seed
        create_result = create_seedance_task(task_payload)
        task_id = create_result.get("id")
        if not task_id:
            raise RuntimeError(f"Ark did not return task id for state {state_id}: {create_result}")
        job["states"][state_id] = {
            "state_id": state_id,
            "label": state.get("label", state_id),
            "status": "submitted",
            "prompt": prompt,
            "task_id": task_id,
            "create_result": create_result,
            "local_video_path": None,
            "local_last_frame_path": None,
        }

    save_job(job)
    return job


def poll_animation_job(job_id: str, download: bool = True) -> dict[str, Any]:
    ensure_dirs()
    job = load_job(job_id)
    character_id = job.get("character", {}).get("id", "character")
    all_terminal = True
    any_failed = False

    for state_id, state in job.get("states", {}).items():
        if state.get("status") in TERMINAL_STATUSES and state.get("local_video_path"):
            continue
        task = get_seedance_task(state["task_id"])
        status = task.get("status", "unknown")
        state["status"] = status
        state["task"] = task
        content = task.get("content") or {}
        video_url = content.get("video_url")
        last_frame_url = content.get("last_frame_url")
        state["video_url"] = video_url
        state["last_frame_url"] = last_frame_url

        if status == "succeeded" and download and video_url and not state.get("local_video_path"):
            video_path = ASSETS_DIR / character_id / f"{state_id}.mp4"
            download_url(video_url, video_path)
            state["local_video_path"] = str(video_path)
            state["local_video_url"] = f"{LOCAL_ASSET_PREFIX}{character_id}/{state_id}.mp4"
        if status == "succeeded" and download and last_frame_url and not state.get("local_last_frame_path"):
            frame_path = ASSETS_DIR / character_id / f"{state_id}_last_frame.png"
            download_url(last_frame_url, frame_path)
            state["local_last_frame_path"] = str(frame_path)
            state["local_last_frame_url"] = f"{LOCAL_ASSET_PREFIX}{character_id}/{state_id}_last_frame.png"

        if status not in TERMINAL_STATUSES:
            all_terminal = False
        if status in {"failed", "cancelled", "canceled", "expired"}:
            any_failed = True

    job["status"] = "failed" if any_failed else ("succeeded" if all_terminal else "running")
    job["updated_at_ms"] = now_ms()
    save_job(job)
    return job


def serve_asset(path_suffix: str) -> tuple[int, bytes, str]:
    safe_parts = [part for part in path_suffix.split("/") if part and part not in {".", ".."}]
    path = (ASSETS_DIR / Path(*safe_parts)).resolve()
    if not str(path).startswith(str(ASSETS_DIR.resolve())) or not path.exists():
        return 404, b"not found", "text/plain"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return 200, path.read_bytes(), mime


def handle_pipeline_get(handler, path: str) -> bool:
    if path == "/pipeline":
        status, payload = json_response({
            "ok": True,
            "service": "BandToy Character Animation Pipeline",
            "endpoints": [
                "POST /pipeline/animations",
                "GET /pipeline/jobs",
                "GET /pipeline/jobs/{job_id}",
                "GET /pipeline/jobs/{job_id}/poll",
                "GET /pipeline/assets/{character_id}/{state}.mp4",
            ],
        })
        handler.send_json_bytes(payload, status)
        return True
    if path == "/pipeline/jobs":
        status, payload = json_response({"jobs": list_jobs()})
        handler.send_json_bytes(payload, status)
        return True
    if path.startswith("/pipeline/jobs/"):
        suffix = path.removeprefix("/pipeline/jobs/").strip("/")
        poll = suffix.endswith("/poll")
        job_id = suffix[:-5].strip("/") if poll else suffix
        try:
            job = poll_animation_job(job_id) if poll else load_job(job_id)
            status, payload = json_response(job)
        except FileNotFoundError:
            status, payload = json_response({"error": "job not found", "job_id": job_id}, 404)
        except Exception as exc:
            status, payload = json_response({"error": str(exc), "job_id": job_id}, 500)
        handler.send_json_bytes(payload, status)
        return True
    if path.startswith(LOCAL_ASSET_PREFIX):
        status, payload, mime = serve_asset(path.removeprefix(LOCAL_ASSET_PREFIX))
        handler.send_bytes(payload, status, mime)
        return True
    return False


def handle_pipeline_post(handler, path: str) -> bool:
    if path != "/pipeline/animations":
        return False
    try:
        body = read_json_body(handler)
        job = create_animation_pipeline(body)
        status, payload = json_response(job, 202)
    except Exception as exc:
        status, payload = json_response({"error": str(exc)}, 500)
    handler.send_json_bytes(payload, status)
    return True
