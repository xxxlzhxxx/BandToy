#!/usr/bin/env python3
"""Run a speaker-to-ESP32 BandToy call-and-response smoke test."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAY_SCRIPT = Path(__file__).with_name("play_twinkle_phrase.py")
DEFAULT_SERVER_LOG = ROOT / "logs" / "recognition-server.log"
DEFAULT_PORT = "/dev/cu.usbmodem3101"
IDF_PYTHON = Path.home() / ".espressif/python_env/idf5.5_py3.14_env/bin/python"
DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def print_line(line: str) -> None:
    print(line, flush=True)


def check_server(base_url: str) -> None:
    with DIRECT_HTTP.open(f"{base_url.rstrip('/')}/health", timeout=3) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if not data.get("ok"):
        raise RuntimeError(f"server health failed: {body}")


def reset_session(base_url: str) -> None:
    try:
        with DIRECT_HTTP.open(f"{base_url.rstrip('/')}/reset_sessions", timeout=3) as response:
            print_line(f"[server] reset_sessions {response.status}")
    except Exception as exc:
        print_line(f"[server] reset_sessions skipped: {exc}")


def tail_file(path: Path, stop: threading.Event, sink: list[str], label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    with path.open("r", encoding="utf-8", errors="replace") as file:
        file.seek(0, os.SEEK_END)
        while not stop.is_set():
            line = file.readline()
            if not line:
                time.sleep(0.1)
                continue
            text = line.rstrip()
            sink.append(text)
            if "recognized" in text or "response_phrase" in text or "/recognize" in text:
                print_line(f"[{label}] {text}")


def serial_reader(port: str, seconds: int, stop: threading.Event, sink: list[str]) -> subprocess.Popen[str] | None:
    if not IDF_PYTHON.exists():
        print_line("[serial] ESP-IDF python not found; skipping serial capture")
        return None
    code = f"""
import serial, time
ser = serial.Serial({port!r}, 115200, timeout=0.2)
end = time.time() + {seconds}
while time.time() < end:
    data = ser.readline()
    if data:
        print(data.decode('utf-8', errors='replace').rstrip(), flush=True)
ser.close()
"""
    process = subprocess.Popen(
        [str(IDF_PYTHON), "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            if stop.is_set():
                break
            text = line.rstrip()
            sink.append(text)
            if any(token in text for token in [
                "display state=",
                "state=",
                "play button pressed",
                "continuous",
                "voice start",
                "voice end",
                "vad waiting",
                "record_until_silence",
                "response_phrase_id",
                "finished phrase",
                "not joining",
                "not playing",
                "discarding weak trigger",
            ]):
                print_line(f"[serial] {text}")

    threading.Thread(target=pump, daemon=True).start()
    return process


def play_phrase(phrase: str, volume: float) -> None:
    subprocess.run([sys.executable, str(PLAY_SCRIPT), phrase, "--volume", str(volume)], check=True)


def summarize(server_lines: list[str], serial_lines: list[str], expected_response: str) -> int:
    combined = "\n".join(server_lines + serial_lines)
    saw_recognize = "\"recognized\": true" in combined or "recognized=1" in combined
    saw_expected = expected_response in combined
    saw_play = "finished phrase" in combined or "song_runtime:" in combined

    print_line("\n[result]")
    print_line(f"recognized: {'yes' if saw_recognize else 'not confirmed'}")
    print_line(f"expected response {expected_response}: {'yes' if saw_expected else 'not confirmed'}")
    print_line(f"device playback: {'yes' if saw_play else 'not confirmed'}")
    return 0 if saw_recognize and saw_expected else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--server-log", type=Path, default=DEFAULT_SERVER_LOG)
    parser.add_argument("--serial-port", default=DEFAULT_PORT)
    parser.add_argument(
        "--phrase",
        default="phrase_1",
        choices=[
            "phrase_1", "phrase_2", "phrase_3", "phrase_4", "phrase_5", "phrase_6",
            "salut_phrase_1", "salut_phrase_2", "salut_phrase_3", "salut_phrase_4",
        ],
    )
    parser.add_argument("--expected-response", default="phrase_2")
    parser.add_argument("--volume", type=float, default=0.24)
    parser.add_argument("--capture-seconds", type=int, default=28)
    parser.add_argument("--start-wait", type=int, default=6)
    parser.add_argument("--manual-boot", action="store_true")
    args = parser.parse_args()

    check_server(args.base_url)
    reset_session(args.base_url)

    stop = threading.Event()
    server_lines: list[str] = []
    serial_lines: list[str] = []
    tail_thread = threading.Thread(target=tail_file, args=(args.server_log, stop, server_lines, "server"), daemon=True)
    tail_thread.start()
    serial_process = serial_reader(args.serial_port, args.capture_seconds, stop, serial_lines)

    if args.manual_boot:
        print_line(f"\nPress BOOT on the ESP32 now. Playing {args.phrase} in {args.start_wait}s...")
    else:
        print_line(f"\nWaiting {args.start_wait}s for auto-listening, then playing {args.phrase}...")
    time.sleep(args.start_wait)
    play_phrase(args.phrase, args.volume)
    time.sleep(max(0, args.capture_seconds - args.start_wait - 5))

    stop.set()
    if serial_process is not None and serial_process.poll() is None:
        serial_process.terminate()
    return summarize(server_lines, serial_lines, args.expected_response)


if __name__ == "__main__":
    raise SystemExit(main())
