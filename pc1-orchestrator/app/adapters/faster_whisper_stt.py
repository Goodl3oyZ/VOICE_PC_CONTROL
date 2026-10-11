"""faster-whisper STT adapter (doc §3.1, §15.1).

The model is loaded once and kept in memory (keep-warm, §14.5). Silero VAD trims silence.
Raw audio is never written to the database (NFR-08): it is decoded from memory and dropped.
Requires `pip install faster-whisper` on PC1.
"""
from __future__ import annotations

import asyncio
import io
import math
import threading
from typing import Any

from ..ports import Transcript

SAMPLE_RATE = 16000


def decode_audio(data: bytes) -> Any:
    """Decode webm/opus, mp4/aac, ogg, wav... from memory to 16 kHz mono float32 (numpy).

    We decode ourselves instead of faster_whisper.decode_audio(): faster-whisper 1.2.1 passes
    `metadata_errors=` to av.open(), which PyAV >= 19 removed — every voice command failed with TypeError.
    Only long-stable PyAV APIs are used here.
    """
    import av
    import numpy as np

    chunks = []
    with av.open(io.BytesIO(data), mode="r") as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            return np.zeros(0, dtype=np.float32)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(stream):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class FasterWhisperSTT:
    def __init__(self, model: str = "small", device: str = "auto", compute_type: str = "int8",
                 language: str | None = "th", initial_prompt: str | None = None):
        self._args = (model, device, compute_type)
        self.language = language
        # Biasing prompt with app names helps transliterated words (§3.1).
        self.initial_prompt = initial_prompt
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # imported lazily: optional dependency
                name, device, compute = self._args
                self._model = WhisperModel(name, device=device, compute_type=compute)
        return self._model

    def warm_up(self) -> None:
        self._load()

    def _run(self, audio: bytes) -> Transcript:
        model = self._load()
        samples = decode_audio(audio)
        if samples.size < SAMPLE_RATE // 10:  # < 0.1 s: nothing to transcribe
            return Transcript(text="", confidence=0.0)
        segments, info = model.transcribe(samples, language=self.language, vad_filter=True,
                                          beam_size=5, initial_prompt=self.initial_prompt)
        texts, logprobs = [], []
        for seg in segments:
            texts.append(seg.text)
            logprobs.append(seg.avg_logprob)
        text = "".join(texts).strip()
        conf = math.exp(sum(logprobs) / len(logprobs)) if logprobs else 0.0
        return Transcript(text=text, confidence=round(conf, 3), lang=info.language)

    async def transcribe(self, audio: bytes, mime: str) -> Transcript:
        return await asyncio.to_thread(self._run, audio)
