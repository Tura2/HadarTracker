from __future__ import annotations

import base64
import json
import logging
import mimetypes

import requests

from hadar_tracker.models import Post, Signal, ThreadItem

OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"

_VALID_ACTIONS = {"buy", "sell", "trim", "add", "watch", "none"}
_VALID_CONVICTIONS = {"low", "medium", "high"}

log = logging.getLogger("hadar_tracker.signal")

__all__ = ["OPENROUTER_ENDPOINT", "DEFAULT_MODEL", "classify_post"]


def classify_post(
    post: Post,
    image_path: str | None,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    vision_model: str | None = None,
) -> Signal | None:
    """Classify a post into a structured trade signal via OpenRouter.

    `model` is used for every post. When `image_path` is set AND
    `vision_model` is given, `vision_model` is used instead — `model` may be
    a text-only model (e.g. DeepSeek's v4 family, which has no image input
    modality on OpenRouter and would otherwise 404 on every image post),
    while `vision_model` (e.g. google/gemini-2.5-flash) actually reads the
    chart. If `vision_model` is None, `model` is used regardless of whether
    there's an image — matching the original single-model behavior.

    Fail-open by design (see the Phase 2 design spec's Error handling
    section): returns None — never raises — if api_key is unset, the HTTP
    call fails, or the response can't be parsed into a Signal. A
    classification problem must never look like a notification-pipeline
    problem to the caller.
    """
    if not api_key:
        return None

    try:
        content: list[dict] = [{"type": "text", "text": _build_prompt(post)}]
        effective_model = model
        if image_path:
            try:
                content.append(_image_content_block(image_path))
                if vision_model:
                    effective_model = vision_model
            except Exception as exc:  # noqa: BLE001 - catch all image-read errors
                log.warning(
                    "could not read image %s for classification: %s", image_path, exc
                )

        response = requests.post(
            OPENROUTER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": effective_model,
                "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        return _to_signal(parsed)
    except Exception as exc:  # noqa: BLE001 - fail-open: never raise out of classify_post
        log.warning("post classification failed for msg_id=%s: %s", post.msg_id, exc)
        return None


def _render_transcript(transcript: tuple[ThreadItem, ...]) -> str:
    if not transcript:
        return "(no thread context available)"
    parts = []
    for item in transcript:
        speaker = "Hadar" if item.author == "hadar" else "Other user"
        subject = item.subject or "(no subject)"
        body = item.body or "(no body)"
        parts.append(f"[{speaker}] {subject}: {body}")
    return " -> ".join(parts)


def _build_prompt(post: Post) -> str:
    tags = ", ".join(post.tags) if post.tags else "(none)"
    return (
        "You are analyzing a forum post by a trader named Hadar on an "
        "Israeli stock trading forum, to determine whether it represents an "
        "actual trade action (buy/sell/trim/add/watch a specific stock) or "
        "is just commentary/noise. Company names are often informal "
        '(e.g. "Aerodrome" for ticker ARDM) — resolve them to a real ticker '
        "symbol using your own knowledge where possible.\n\n"
        f"Thread so far: {_render_transcript(post.thread_transcript)}\n\n"
        "Hadar's post being classified:\n"
        f"Subject: {post.subject or '(none)'}\n"
        f"Body: {post.body or '(none)'}\n"
        f"Tags: {tags}\n\n"
        "Respond with ONLY a JSON object with exactly these fields:\n"
        '{"is_signal": bool, "ticker_mentioned": string or null, '
        '"ticker_guess": string or null, '
        '"action": one of "buy"/"sell"/"trim"/"add"/"watch"/"none", '
        '"conviction": one of "low"/"medium"/"high", '
        '"price_levels": string or null, "rationale": short string}'
    )


def _image_content_block(image_path: str) -> dict:
    mime_type, _ = mimetypes.guess_type(image_path)
    mime_type = mime_type or "image/jpeg"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
    }


def _to_signal(parsed: dict) -> Signal:
    action = parsed.get("action")
    if action not in _VALID_ACTIONS:
        action = "none"
    conviction = parsed.get("conviction")
    if conviction not in _VALID_CONVICTIONS:
        conviction = "low"
    return Signal(
        is_signal=bool(parsed.get("is_signal", False)),
        ticker_mentioned=parsed.get("ticker_mentioned"),
        ticker_guess=parsed.get("ticker_guess"),
        action=action,
        conviction=conviction,
        price_levels=parsed.get("price_levels"),
        rationale=str(parsed.get("rationale") or ""),
    )
