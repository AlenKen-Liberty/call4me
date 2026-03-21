"""Speculative TTS cache: pre-generates audio for predicted next responses."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from call4me.llm import Chat2APIClient
from call4me.tts import PiperTTS
from .script import CallScript, ScriptNode

logger = logging.getLogger("call4me.planner")

# How many speculative responses to pre-generate per turn
MAX_SPECULATIVE = 3

PREDICT_PROMPT = """\
You are predicting how a phone conversation will continue.

Context:
{script_context}

Conversation so far:
{history_text}

The last thing they said was: "{last_heard}"

Predict the {n} most likely things they will say next, and for each, what
our best response should be.

Output JSON array (no extra text):
[
  {{"trigger": "what they might say", "response": "what we should say back"}},
  ...
]

Rules:
- Responses must be EXACT spoken words (short, natural speech)
- Keep responses under 2 sentences
- Be practical — predict the MOST likely continuations
"""


class SpeculativeCache:
    """Background thread that pre-generates TTS for predicted responses.

    During a call, after each exchange, it predicts what the other party
    might say next, generates our responses, and caches the TTS audio.
    When the actual response comes in, we check if any cached audio
    matches — if so, we play it instantly (zero TTS latency).
    """

    def __init__(
        self,
        llm: Chat2APIClient,
        tts: PiperTTS,
        script: CallScript | None = None,
    ):
        self.llm = llm
        self.tts = tts
        self.script = script
        self._cache: dict[str, tuple[str, Path]] = {}  # trigger -> (response, wav)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._recent_responses: list[str] = []  # last N responses used, to avoid repeats

    def precache_script(self, script: CallScript) -> int:
        """Pre-generate TTS for unique responses in the script. Returns count.

        Deduplicates by response content — if two nodes say essentially the
        same thing, only one WAV is generated.  The trigger mapping still
        covers both so either can match.
        """
        self.script = script
        count = 0
        # response_norm -> (wav_path, original_text)
        seen_responses: dict[str, tuple[Path, str]] = {}

        for node in script.all_nodes():
            resp = node.response.strip()
            if not resp:
                continue

            resp_norm = self._normalize_text(resp)

            # Check for near-duplicate responses (>70% word overlap)
            dup_wav = self._find_duplicate(resp_norm, seen_responses)
            if dup_wav is not None:
                node.cached_wav = str(dup_wav)
                with self._lock:
                    key = self._normalize_trigger(node.trigger)
                    self._cache[key] = (resp, dup_wav)
                logger.debug("Dedup [%s]: reusing WAV for: %s", node.id, resp[:40])
                continue

            try:
                wav = self.tts.synthesize(resp)
                node.cached_wav = str(wav)
                seen_responses[resp_norm] = (wav, resp)
                with self._lock:
                    key = self._normalize_trigger(node.trigger)
                    self._cache[key] = (resp, wav)
                count += 1
                logger.info("Pre-cached [%s]: %s", node.id, resp[:60])
            except Exception as exc:
                logger.warning("Failed to cache node %s: %s", node.id, exc)
        return count

    @staticmethod
    def _find_duplicate(
        resp_norm: str, seen: dict[str, tuple[Path, str]]
    ) -> Path | None:
        """Return the WAV path if resp_norm is >60% similar to something seen."""
        resp_words = set(resp_norm.split())
        if not resp_words:
            return None
        for existing_norm, (wav, _) in seen.items():
            existing_words = set(existing_norm.split())
            if not existing_words:
                continue
            overlap = resp_words & existing_words
            union = resp_words | existing_words
            similarity = len(overlap) / len(union) if union else 0
            if similarity > 0.6:
                return wav
        return None

    def match(self, heard: str) -> tuple[str, Path] | None:
        """Try to match what we heard against cached responses.

        Returns (response_text, wav_path) if a match is found.
        Skips responses used in the last 3 turns to avoid repetition.
        """
        heard_norm = self._normalize_text(heard)
        heard_words = set(heard_norm.split())

        best_match: tuple[str, Path] | None = None
        best_score = 0.0

        with self._lock:
            for trigger_key, (response, wav) in self._cache.items():
                # Skip responses we've recently used
                resp_norm = self._normalize_text(response)
                if resp_norm in self._recent_responses:
                    continue
                score = self._match_score(heard_norm, heard_words, trigger_key)
                if score > best_score and score >= 0.55:
                    best_score = score
                    best_match = (response, wav)

        if best_match:
            # Track this response to avoid reusing it soon
            resp_norm = self._normalize_text(best_match[0])
            self._recent_responses.append(resp_norm)
            if len(self._recent_responses) > 3:
                self._recent_responses.pop(0)
            logger.info(
                "Cache HIT (score=%.2f): heard=%r -> response=%r",
                best_score, heard[:50], best_match[0][:50],
            )
        return best_match

    def speculate_async(
        self,
        history: list[dict[str, str]],
        last_heard: str,
    ) -> None:
        """Launch background speculation for next turn responses."""
        if self._worker and self._worker.is_alive():
            return  # already working

        self._worker = threading.Thread(
            target=self._speculate_worker,
            args=(list(history), last_heard),
            daemon=True,
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=3)

    def _speculate_worker(
        self,
        history: list[dict[str, str]],
        last_heard: str,
    ) -> None:
        """Background worker: predict next exchanges and pre-cache TTS."""
        try:
            predictions = self._predict_next(history, last_heard)
            for trigger, response in predictions:
                if self._stop.is_set():
                    break
                try:
                    wav = self.tts.synthesize(response)
                    key = self._normalize_trigger(trigger)
                    with self._lock:
                        self._cache[key] = (response, wav)
                    logger.info("Speculative cache: [%s] -> %s", trigger[:30], response[:40])
                except Exception as exc:
                    logger.debug("Speculative TTS failed: %s", exc)
        except Exception as exc:
            logger.debug("Speculation failed: %s", exc)

    def _predict_next(
        self,
        history: list[dict[str, str]],
        last_heard: str,
    ) -> list[tuple[str, str]]:
        """Ask LLM to predict likely next exchanges."""
        history_text = "\n".join(
            f"{'Them' if m['role'] == 'user' else 'Us'}: {m['content']}"
            for m in history[-6:]
        )
        script_context = ""
        if self.script:
            script_context = f"Purpose: {self.script.plan.purpose}\nTone: {self.script.plan.tone}"

        prompt = PREDICT_PROMPT.format(
            script_context=script_context,
            history_text=history_text,
            last_heard=last_heard,
            n=MAX_SPECULATIVE,
        )

        import json

        raw = self.llm.complete_text(
            prompt,
            max_output_tokens=400,
            temperature=0.3,
        )

        # Parse JSON array
        try:
            if "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            return [
                (item["trigger"], item["response"])
                for item in data
                if "trigger" in item and "response" in item
            ]
        except (json.JSONDecodeError, KeyError):
            return []

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize heard text for matching."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _normalize_trigger(text: str) -> str:
        """Normalize trigger patterns while preserving slash-separated alternatives."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s/]", "", text)
        text = re.sub(r"\s*/\s*", " / ", text)
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _match_score(heard_norm: str, heard_words: set[str], trigger_key: str) -> float:
        """Score how well heard text matches a trigger pattern.

        Triggers can contain "/" separated alternatives (e.g. "hello / hi / hey").
        """
        # Split trigger by "/" for alternatives
        alternatives = [alt.strip() for alt in trigger_key.split("/") if alt.strip()]
        if not alternatives:
            alternatives = [trigger_key]

        best = 0.0
        for alt in alternatives:
            alt_words = set(alt.split())
            if not alt_words:
                continue

            # Exact substring match
            if alt in heard_norm:
                score = 0.9
            else:
                # Word overlap (Jaccard-like)
                overlap = heard_words & alt_words
                if not overlap:
                    continue
                # Weighted: how much of the trigger is covered
                coverage = len(overlap) / len(alt_words)
                score = coverage * 0.7

            best = max(best, score)

        return best

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)
