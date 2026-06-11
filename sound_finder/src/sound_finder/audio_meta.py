from __future__ import annotations

import contextlib
import math
import wave
from array import array
from pathlib import Path
from typing import Any


def read_duration_seconds(path: Path) -> float | None:
    """Return duration for formats we can inspect without extra dependencies."""
    suffix = path.suffix.lower()
    if suffix != ".wav":
        return None

    with contextlib.suppress(Exception):
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if rate:
                return frames / float(rate)

    return None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    rest = seconds - minutes * 60
    return f"{minutes}:{rest:04.1f}"


def _dbfs(value: float) -> float | None:
    if value <= 0:
        return None
    return 20.0 * math.log10(value)


def _format_db(value: float | None, suffix: str = " dBFS") -> str:
    if value is None:
        return "未知"
    return f"{value:.1f}{suffix}"


def format_audio_analysis(analysis: dict[str, Any]) -> str:
    if analysis.get("error"):
        return str(analysis["error"])
    peak_label = "Peak≈" if analysis.get("sampled") else "Peak"
    rms_label = "RMS≈" if analysis.get("sampled") else "RMS"
    parts = [
        f"Ch: {analysis.get('channels', '未知')}",
        f"SR: {analysis.get('sample_rate', '未知')} Hz",
        f"Bit: {analysis.get('bit_depth', '未知')}",
        f"Duration: {format_duration(analysis.get('duration')) or '未知'}",
        f"{peak_label}: {_format_db(analysis.get('peak_dbfs'))}",
        f"{rms_label}: {_format_db(analysis.get('rms_dbfs'))}",
        f"LUFS-I≈: {_format_db(analysis.get('lufs_i_approx'), ' LUFS')}",
    ]
    if analysis.get("sampled"):
        parts.append("分析: 抽样")
    return "    ".join(parts)


def analyze_wav(path: Path, max_points: int = 1200, max_samples: int = 1_000_000) -> dict[str, Any]:
    """Read basic PCM WAV stats and a compact absolute-peak waveform.

    Short files are scanned exactly. Long files are sampled across the timeline
    so selecting a large ambience does not freeze the UI.
    """
    try:
        handle = wave.open(str(path), "rb")
    except Exception as exc:
        return {"error": f"无法读取音频参数: {exc}", "waveform": []}

    with handle:
        channels = handle.getnchannels()
        sample_rate = handle.getframerate()
        sample_width = handle.getsampwidth()
        frames = handle.getnframes()
        comp_type = handle.getcomptype()
        if comp_type != "NONE":
            return {"error": f"暂不支持压缩 WAV: {comp_type}", "waveform": []}
        if frames <= 0 or channels <= 0:
            return {"error": "空音频文件", "waveform": []}
        if sample_width not in {1, 2, 3, 4}:
            return {"error": "暂不支持该 WAV 位深", "waveform": []}

        total_samples = frames * channels
        sampled = total_samples > max_samples
        waveform = [0.0 for _ in range(min(max_points, frames))]
        full_scale = float(1 << (sample_width * 8 - 1))
        peak = 0
        sum_sq = 0.0
        measured_samples = 0

        def add_sample(frame_index: int, value: int) -> None:
            nonlocal peak, sum_sq, measured_samples
            absolute = abs(value)
            if absolute > peak:
                peak = absolute
            sum_sq += float(value) * float(value)
            measured_samples += 1
            bucket = min(int(frame_index * len(waveform) / frames), len(waveform) - 1)
            normalized = min(1.0, absolute / full_scale)
            if normalized > waveform[bucket]:
                waveform[bucket] = normalized

        def process_bytes(data: bytes, first_frame: int) -> None:
            if sample_width == 1:
                for index, byte in enumerate(data):
                    frame_index = first_frame + index // channels
                    add_sample(frame_index, int(byte) - 128)
            elif sample_width == 2:
                samples = array("h")
                samples.frombytes(data)
                for index, value in enumerate(samples):
                    frame_index = first_frame + index // channels
                    add_sample(frame_index, int(value))
            elif sample_width == 4:
                samples = array("i")
                samples.frombytes(data)
                for index, value in enumerate(samples):
                    frame_index = first_frame + index // channels
                    add_sample(frame_index, int(value))
            else:
                for index, offset in enumerate(range(0, len(data), 3)):
                    raw = data[offset : offset + 3]
                    sign = b"\x00" if raw[-1] < 0x80 else b"\xff"
                    value = int.from_bytes(raw + sign, "little", signed=True)
                    frame_index = first_frame + index // channels
                    add_sample(frame_index, value)

        if sampled:
            max_frames_to_read = max(1, max_samples // channels)
            windows = max(1, min(max_points, frames, max_frames_to_read))
            chunk_frames = max(1, max_frames_to_read // windows)
            for window in range(windows):
                start_frame = int(window * frames / windows)
                handle.setpos(min(start_frame, frames - 1))
                data = handle.readframes(min(chunk_frames, frames - start_frame))
                if data:
                    process_bytes(data, start_frame)
        else:
            frames_done = 0
            chunk_frames = 32768
            while frames_done < frames:
                data = handle.readframes(min(chunk_frames, frames - frames_done))
                if not data:
                    break
                process_bytes(data, frames_done)
                frames_done += len(data) // (sample_width * channels)

    peak_linear = min(1.0, peak / full_scale)
    rms_linear = math.sqrt(sum_sq / measured_samples) / full_scale if measured_samples else 0.0
    rms_dbfs = _dbfs(rms_linear)
    return {
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width": sample_width,
        "bit_depth": sample_width * 8,
        "frame_count": frames,
        "duration": frames / float(sample_rate) if sample_rate else None,
        "peak_dbfs": _dbfs(peak_linear),
        "rms_dbfs": rms_dbfs,
        "lufs_i_approx": (rms_dbfs - 0.691) if rms_dbfs is not None else None,
        "waveform": waveform,
        "sampled": sampled,
    }


def analyze_audio(path: Path, max_points: int = 1200) -> dict[str, Any]:
    if path.suffix.lower() != ".wav":
        return {
            "error": "当前仅对 WAV 计算波形、Peak、RMS 和近似 LUFS；其他格式仍可试听。",
            "waveform": [],
        }
    return analyze_wav(path, max_points=max_points)
