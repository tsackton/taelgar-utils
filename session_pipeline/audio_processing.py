from __future__ import annotations

import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from pydub import AudioSegment

RNNOISE_URL = "https://raw.githubusercontent.com/richardpl/arnndn-models/master/std.rnnn"
RNNOISE_DEFAULT_NAME = "std.rnnn"
RNNOISE_CACHE_DIR = Path.home() / ".cache" / "taelgar" / "rnnoise"


class AudioProcessingError(RuntimeError):
    """Raised when ffmpeg or normalisation fails."""


@dataclass(frozen=True)
class AudioProfileConfig:
    mode: str  # "ffmpeg" or "normalize"
    highpass: Optional[int] = None
    lowpass: Optional[int] = None
    denoise: Optional[Dict[str, str]] = None
    dynaudnorm: Optional[Dict[str, str]] = None
    compressor: Optional[Dict[str, str]] = None
    target_dbfs: float = -10.0
    headroom_db: float = 1.0


AUDIO_PROFILES: Dict[str, AudioProfileConfig] = {
    "passthrough": AudioProfileConfig(mode="ffmpeg"),
    "normalize-only": AudioProfileConfig(mode="normalize", target_dbfs=-10.0, headroom_db=1.0),
    "zoom-audio": AudioProfileConfig(
        mode="ffmpeg",
        highpass=100,
        lowpass=7500,
        denoise={"type": "afftdn", "args": "nf=-25"},
        dynaudnorm={"f": "250", "g": "12"},
        compressor={"threshold": "-18dB", "ratio": "2", "attack": "60", "release": "250"},
    ),
    "voice-memo": AudioProfileConfig(
        mode="ffmpeg",
        highpass=80,
        lowpass=8000,
        denoise={"type": "arnndn", "model": RNNOISE_DEFAULT_NAME},
        dynaudnorm={"f": "150", "g": "15"},
        compressor={"threshold": "-21dB", "ratio": "3", "attack": "100", "release": "500"},
    ),
}

SUPPORTED_OUTPUT_FORMATS = {"wav", "flac"}


def preprocess_audio_file(
    source_path: Path,
    output_path: Path,
    *,
    profile: str,
    sample_rate: int = 16_000,
    channels: int = 1,
    sample_width: int = 2,
    output_format: str = "wav",
    overwrite: bool = False,
    highpass: Optional[int] = None,
    lowpass: Optional[int] = None,
    disable_denoise: bool = False,
    disable_dynaudnorm: bool = False,
    disable_compression: bool = False,
    rnnoise_model_path: Optional[Path] = None,
) -> Path:
    """
    Preprocess ``source_path`` into ``output_path`` according to ``profile``.
    """

    source_path = Path(source_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()

    if not source_path.exists():
        raise AudioProcessingError(f"Audio source not found: {source_path}")

    if output_path.exists() and not overwrite:
        raise AudioProcessingError(f"Output exists: {output_path}")

    profile_config = AUDIO_PROFILES.get(profile)
    if profile_config is None:
        raise AudioProcessingError(f"Unknown audio profile '{profile}'.")

    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise AudioProcessingError(f"Output format '{output_format}' is not supported.")

    if sample_width != 2:
        raise AudioProcessingError("Only 16-bit PCM output is currently supported.")

    if channels not in (1, 2):
        raise AudioProcessingError("Channels must be 1 (mono) or 2 (stereo).")

    if profile_config.mode == "normalize":
        _normalise_audio_in_memory(
            source_path,
            output_path,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            output_format=output_format,
            target_dbfs=profile_config.target_dbfs,
            headroom_db=profile_config.headroom_db,
            overwrite=overwrite,
        )
        return output_path

    filter_chain = _build_filter_chain(
        profile_config,
        highpass=highpass,
        lowpass=lowpass,
        disable_denoise=disable_denoise,
        disable_dynaudnorm=disable_dynaudnorm,
        disable_compression=disable_compression,
        rnnoise_model_path=rnnoise_model_path,
    )

    _run_ffmpeg(
        source_path,
        output_path,
        sample_rate=sample_rate,
        channels=channels,
        output_format=output_format,
        filters=filter_chain,
        overwrite=overwrite,
    )
    return output_path


def ensure_rnnoise_model(model_name: str = RNNOISE_DEFAULT_NAME) -> Path:
    target = RNNOISE_CACHE_DIR / model_name
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            urllib.request.urlretrieve(RNNOISE_URL, tmp.name)
            tmp.flush()
            tmp_path = Path(tmp.name)
        tmp_path.replace(target)
    except Exception as exc:  # pragma: no cover - network failures
        raise AudioProcessingError(f"Failed to download rnnoise model: {exc}") from exc

    return target


def _normalise_audio_in_memory(
    source_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    channels: int,
    sample_width: int,
    output_format: str,
    target_dbfs: float,
    headroom_db: float,
    overwrite: bool,
) -> None:
    if output_path.exists() and not overwrite:
        raise AudioProcessingError(f"Output exists: {output_path}")

    audio = AudioSegment.from_file(source_path)
    change_in_dbfs = target_dbfs - audio.dBFS
    normalised = audio.apply_gain(change_in_dbfs)
    peak_dbfs = normalised.max_dBFS
    if peak_dbfs > (-headroom_db):
        clipping_gain = (-headroom_db) - peak_dbfs
        normalised = normalised.apply_gain(clipping_gain)

    normalised = normalised.set_frame_rate(sample_rate).set_channels(channels).set_sample_width(sample_width)
    export_handle = normalised.export(output_path, format=output_format)
    export_handle.close()


def _build_filter_chain(
    profile_config: AudioProfileConfig,
    *,
    highpass: Optional[int],
    lowpass: Optional[int],
    disable_denoise: bool,
    disable_dynaudnorm: bool,
    disable_compression: bool,
    rnnoise_model_path: Optional[Path],
) -> Optional[str]:
    filters = []
    hp = highpass if highpass is not None else profile_config.highpass
    if hp:
        filters.append(f"highpass=f={hp}")
    lp = lowpass if lowpass is not None else profile_config.lowpass
    if lp:
        filters.append(f"lowpass=f={lp}")

    if profile_config.denoise and not disable_denoise:
        denoise = profile_config.denoise
        if denoise["type"] == "arnndn":
            model_path = rnnoise_model_path or ensure_rnnoise_model(denoise.get("model", RNNOISE_DEFAULT_NAME))
            filters.append(f"arnndn=m={model_path}")
        elif denoise["type"] == "afftdn":
            args = denoise.get("args", "")
            filters.append(f"afftdn={args}" if args else "afftdn")

    if profile_config.dynaudnorm and not disable_dynaudnorm:
        dyna = profile_config.dynaudnorm
        f = dyna.get("f", "250")
        g = dyna.get("g", "12")
        filters.append(f"dynaudnorm=f={f}:g={g}")

    if profile_config.compressor and not disable_compression:
        comp = profile_config.compressor
        threshold = comp.get("threshold", "-18dB")
        ratio = comp.get("ratio", "2")
        attack = comp.get("attack", "50")
        release = comp.get("release", "250")
        filters.append(
            f"acompressor=threshold={threshold}:ratio={ratio}:attack={attack}:release={release}"
        )

    return ",".join(filters) if filters else None


def _run_ffmpeg(
    source_path: Path,
    output_path: Path,
    *,
    sample_rate: int,
    channels: int,
    output_format: str,
    filters: Optional[str],
    overwrite: bool,
) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
    ]
    if filters:
        cmd.extend(["-af", filters])

    if output_format == "wav":
        cmd.extend(["-c:a", "pcm_s16le"])
    elif output_format == "flac":
        cmd.extend(["-c:a", "flac"])
    else:  # pragma: no cover - guarded earlier
        raise AudioProcessingError(f"Unsupported format '{output_format}'")

    cmd.append(str(output_path))

    if overwrite:
        cmd.insert(1, "-y")
    else:
        cmd.insert(1, "-n")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioProcessingError(result.stderr.strip() or "ffmpeg failed")


def iter_audio_files(paths: Iterable[Path], *, extensions: Iterable[str]) -> Iterable[Path]:
    allowed = {ext.lower() for ext in extensions}
    for path in paths:
        path = path.expanduser().resolve()
        if path.is_file() and path.suffix.lower() in allowed:
            yield path
        elif path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and child.suffix.lower() in allowed:
                    yield child


def default_clean_path(
    source_path: Path,
    *,
    suffix: str = "-clean",
    extension: str = ".wav",
    output_dir: Optional[Path] = None,
) -> Path:
    destination_dir = (output_dir or source_path.parent).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    ext = extension if extension.startswith(".") else f".{extension}"
    return destination_dir / f"{source_path.stem}{suffix}{ext}"


def prepare_clean_audio(
    source_path: Path,
    *,
    profile: str,
    discard: bool,
    sample_rate: int = 16_000,
    channels: int = 1,
    output_format: str = "wav",
    log_fn: Optional[Callable[[str], None]] = None,
) -> tuple[Path, Optional[Path]]:
    """
    Preprocess ``source_path`` using ``profile`` and return the clean path plus optional cleanup marker.

    When ``discard`` is True, the cleaned audio is written to a temporary file that callers should delete.
    Otherwise the cleaned audio is written beside the source with ``-clean`` appended to the basename.
    """

    source_path = Path(source_path).expanduser().resolve()
    if discard:
        temp_file = tempfile.NamedTemporaryFile(prefix=f"{source_path.stem}-clean-", suffix=f".{output_format}", delete=False)
        temp_file.close()
        clean_path = Path(temp_file.name)
        cleanup_path: Optional[Path] = clean_path
        overwrite = True
    else:
        clean_path = default_clean_path(source_path, extension=output_format)
        cleanup_path = None
        overwrite = False
        if clean_path.exists():
            raise AudioProcessingError(
                f"Preprocessed audio already exists: {clean_path} (rerun with --discard-audio to overwrite)."
            )

    if log_fn:
        log_fn(f"Preprocessing {source_path} with profile {profile} -> {clean_path}")

    preprocess_audio_file(
        source_path,
        clean_path,
        profile=profile,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=2,
        output_format=output_format,
        overwrite=overwrite,
    )

    return clean_path, cleanup_path


__all__ = [
    "AUDIO_PROFILES",
    "AudioProcessingError",
    "preprocess_audio_file",
    "ensure_rnnoise_model",
    "iter_audio_files",
    "SUPPORTED_OUTPUT_FORMATS",
    "default_clean_path",
    "prepare_clean_audio",
]
