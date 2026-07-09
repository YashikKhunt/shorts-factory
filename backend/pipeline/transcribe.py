"""faster-whisper transcription with multi-signal no-speech detection.

Raw trip footage is usually wind/ambience; Whisper hallucinates phrases like
"Thanks for watching" on it, so we only trust the transcript when several
independent signals agree there is real speech.
"""
from pathlib import Path

_model = None
_model_key = None


def _get_model(cfg):
    global _model, _model_key
    key = (cfg.whisper.model, cfg.whisper.compute_type)
    if _model is None or _model_key != key:
        from faster_whisper import WhisperModel
        _model = WhisperModel(cfg.whisper.model, device="cpu",
                              compute_type=cfg.whisper.compute_type)
        _model_key = key
    return _model


def transcribe(wav: Path, cfg) -> list[tuple[float, float, str]] | None:
    """Return [(start, end, text)] or None when the clip has no usable speech."""
    model = _get_model(cfg)
    segments, _info = model.transcribe(str(wav), vad_filter=True,
                                       word_timestamps=False)
    segs = list(segments)
    if not segs:
        return None

    speech_dur = sum(s.end - s.start for s in segs)
    mean_no_speech = sum(s.no_speech_prob for s in segs) / len(segs)
    words = " ".join(s.text for s in segs).split()
    low_conf = all(s.avg_logprob < -1.0 for s in segs)

    if speech_dur < cfg.whisper.min_speech_seconds:
        return None
    if mean_no_speech > cfg.whisper.max_no_speech_prob:
        return None
    if len(words) < 4 and low_conf:
        return None
    return [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]
