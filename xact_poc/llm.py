"""Thin client for OpenCode Zen's Anthropic-format endpoint, with a cost ledger."""
import asyncio
import base64
import io
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()  # iPhone photos
except ImportError:
    pass

ANTHROPIC_URL = "https://opencode.ai/inference/anthropic/v1/messages"
OPENAI_URL = "https://opencode.ai/inference/openai/v1/chat/completions"

# $ per 1M tokens (input, output), from opencode.ai/docs/zen
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "deepseek-v4.1-flash": (0.30, 1.20),
    "deepseek-v4.1-flash-free": (0.0, 0.0),
}

CHEAP = "claude-haiku-5-5"
SMART = "claude-sonnet-5-5"
FRONTIER = "claude-opus-5-5"


def api_key() -> str:
    if key := os.environ.get("ZEN_API_KEY"):
        return key
    env = Path(__file__).parent.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ZEN_API_KEY="):
                return line.split("=", 1)[1].strip()
    auth = Path.home() / ".local/share/opencode/auth.json"
    return json.loads(auth.read_text())["opencode"]["key"]


@dataclass
class Ledger:
    calls: list[dict] = field(default_factory=list)

    def add(self, stage: str, model: str, usage: dict):
        pin, pout = PRICES[model]
        tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        self.calls.append(
            {"stage": stage, "model": model, "in": tin, "out": tout,
             "usd": tin / 1e6 * pin + tout / 1e6 * pout}
        )

    def summary(self) -> dict:
        out: dict[str, dict] = {}
        for c in self.calls:
            # Keyed by stage + model so a stage run with two models (or a retry on another) isn't mispriced.
            key = c["stage"] if all(x["model"] == c["model"] for x in self.calls if x["stage"] == c["stage"]) \
                else f"{c['stage']} ({c['model']})"
            s = out.setdefault(key, {"model": c["model"], "calls": 0, "in": 0, "out": 0, "usd": 0.0})
            s["calls"] += 1
            s["in"] += c["in"]
            s["out"] += c["out"]
            s["usd"] += c["usd"]
        return out

    def total(self) -> float:
        return sum(c["usd"] for c in self.calls)


def image_block(path: Path, max_side: int = 1092) -> dict:
    """Downscale before sending: ~1.2k tokens per photo instead of ~5k."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    data = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def to_openai(msg: dict) -> dict:
    if isinstance(msg["content"], str):
        return msg
    parts = []
    for b in msg["content"]:
        if b["type"] == "image":
            src = b["source"]
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{src['media_type']};base64,{src['data']}"}})
        else:
            parts.append({"type": "text", "text": b["text"]})
    return {"role": msg["role"], "content": parts}


def parse_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    text = m.group(1) if m else text
    start = min(i for i in (text.find("{"), text.find("[")) if i != -1)
    return json.loads(text[start:])


class Client:
    def __init__(self, ledger: Ledger, concurrency: int = 8):
        self.ledger = ledger
        self.sem = asyncio.Semaphore(concurrency)
        self.key = api_key()
        self.http = httpx.AsyncClient(
            timeout=300,
            headers={"x-api-key": self.key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
        )

    async def _send(self, model: str, system: str, messages: list, max_tokens: int):
        """Returns (status, text, usage); hides the Anthropic vs OpenAI wire formats."""
        if model.startswith("claude"):
            body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
            r = await self.http.post(ANTHROPIC_URL, json=body)
            if r.status_code != 200:
                return r, None, None
            data = r.json()
            text = "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")
            return r, text, data.get("usage", {})
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}] + [to_openai(m) for m in messages]}
        r = await self.http.post(OPENAI_URL, json=body,
                                 headers={"authorization": f"Bearer {self.key}"})
        if r.status_code != 200:
            return r, None, None
        data = r.json()
        u = data.get("usage", {})
        usage = {"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0)}
        return r, data["choices"][0]["message"]["content"], usage

    async def json_call(self, stage: str, model: str, system: str, content: list | str,
                        max_tokens: int = 4000, retries: int = 3):
        messages = [{"role": "user", "content": content}]
        async with self.sem:
            for attempt in range(retries):
                r, text, usage = await self._send(model, system, messages, max_tokens)
                if r.status_code in (429, 500, 502, 503, 529):
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                r.raise_for_status()
                self.ledger.add(stage, model, usage)
                try:
                    return parse_json(text)
                except (ValueError, json.JSONDecodeError):
                    if attempt == retries - 1:
                        raise
                    messages = messages[:1] + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": "That was not valid JSON. Reply with only the JSON."},
                    ]
            r.raise_for_status()

    async def close(self):
        await self.http.aclose()
