import asyncio
import base64
import mimetypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from data.config import ROOT_DIR
from data.settings import Settings


# --- поиск ffmpeg ---
def _validate_ffmpeg(path: str) -> bool:
    try:
        out = subprocess.run(
            [path, "-version"], capture_output=True, text=True, timeout=3
        )
        return out.returncode == 0 and "ffmpeg" in (out.stdout + out.stderr).lower()
    except Exception:
        return False


def resolve_ffmpeg_path() -> Optional[str]:
    cand: list[str] = []

    # 1) Settings
    p = getattr(Settings(), "ffmpeg_path", None)
    if p:
        cand.append(str(p))

    # 2) ENV
    envp = os.getenv("FFMPEG_PATH")
    if envp:
        cand.append(envp)

    # 3) PATH
    which = shutil.which("ffmpeg")
    if which:
        cand.append(which)

    # 4) локальные bin
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    cand += [
        str(ROOT_DIR / "bin" / exe),
        str(ROOT_DIR / "files" / "bin" / exe),
        str(Path.cwd() / "bin" / exe),
    ]

    # 5) типичные системные пути
    if sys.platform.startswith("win"):
        cand += [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        ]
    elif sys.platform == "darwin":
        cand += ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]
    else:
        cand += ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/snap/bin/ffmpeg"]

    seen = set()
    for c in cand:
        if not c or c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c) and os.access(c, os.X_OK) and _validate_ffmpeg(c):
            return c
    return None


# --- транскод ---
_EXT_TO_FFMT = {
    "mp3": "mp3",
    "wav": "wav",
    "ogg": "ogg",
    "opus": "ogg",
    "m4a": "mp4",
    "aac": "aac",
    "webm": "webm",
}


async def transcode_bytes_to_webm_opus(
    audio_bytes: bytes,
    *,
    input_ext: Optional[str] = None,
    bitrate: str = "96k",
    mono: bool = True,
    sample_rate: int = 48000,
    passthrough_if_missing: bool = True,
) -> bytes:
    """
    Конвертирует байты аудио → webm/opus (байты).
    Если ffmpeg не найден → возвращает оригинал (если passthrough_if_missing=True).
    """
    if not audio_bytes:
        raise ValueError("audio_bytes is empty")

    ffmpeg = resolve_ffmpeg_path()
    if not ffmpeg:
        logger.debug("[ffmpeg] not found. Passthrough original bytes.")
        if passthrough_if_missing:
            return audio_bytes
        raise RuntimeError("ffmpeg not found")

    args = [ffmpeg, "-hide_banner", "-loglevel", "error"]

    if input_ext:
        f = _EXT_TO_FFMT.get(input_ext.lower())
        if f:
            args += ["-f", f]

    args += [
        "-i",
        "pipe:0",
        "-vn",
        "-map",
        "0:a:0",
        "-c:a",
        "libopus",
        "-b:a",
        bitrate,
        "-ar",
        str(sample_rate),
        "-ac",
        "1" if mono else "2",
        "-application",
        "audio",
        "-vbr",
        "on",
        "-compression_level",
        "10",
        "-f",
        "webm",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    out, err = await proc.communicate(input=audio_bytes)

    if proc.returncode != 0:
        logger.error(
            f"[ffmpeg] failed ({proc.returncode}): {err.decode('utf-8', 'ignore')}"
        )
        if passthrough_if_missing:
            return audio_bytes
        raise RuntimeError(f"ffmpeg transcode failed: {proc.returncode}")

    return out


# --- удобный бандл для отправки в JSON ---
def make_desc_bytes(b: bytes, ext: str = "webm", save_dir: bool = False) -> dict:
    ts = int(time.time() * 1000)
    filename = f"audio_recording_{ts}.{ext}"

    mime, _ = mimetypes.guess_type(filename)
    if not mime or not mime.startswith("audio/"):
        mime = "audio/webm"

    b64 = base64.b64encode(b).decode("ascii")

    if save_dir:
        out_dir = ROOT_DIR / PROFILES_DIR / "audio_recordings"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / filename).write_bytes(b)

    return {
        "b64": f"data:{mime};base64,{b64}",
        "mime": mime,
        "filename": filename,
    }
