from __future__ import annotations

import json
import re
from typing import Iterator

import httpx

OLLAMA_BASE = "http://localhost:11434"

SYSTEM_PROMPT = """You are an expert in mass spectrometry-based metabolomics study design.

## Tools
You have three tools. Always call them in this order:
  1. set_samples
  2. configure_run
  3. generate_sequence

## Step 1 — set_samples
Extract every sample name and all biological metadata from the user's input.
If multiple biological factors exist (e.g. treatment + sex), combine them into ONE composite
group label per sample (e.g. "KO_male", "WT_female"). This composite group is the
stratification key used to balance groups across QC blocks.
Infer batch from any plate/day/batch labels. Default batch=1 if not mentioned.

## Step 2 — configure_run
Choose settings based on the study:
- qc_frequency: 5 for <30 samples, 8 for 30-60, 10 for >60
- qc_at_start: always 3 (instrument equilibration)
- qc_at_end: always 1
- blank_at_start / blank_at_end: always true
- blank_frequency: 0 unless matrix contamination carry-over is a concern
- wash_after_blank: always true
- randomize_samples: always true
- stratify_by_group: true whenever group information is present; false only if no groups exist
- block_by_batch: true whenever multiple batches exist

## Step 3 — generate_sequence
Always call this after configure_run.

## Final response (required)
After all tool calls, write a short explanation covering:
- How many samples you registered and what groups/batches you identified
- The composite group labels you created and which biological factors they encode
- The QC frequency you chose and the reasoning (study size, number of injections)
- Whether stratification was applied and why it protects this specific study against drift
- Any assumptions you made about ambiguous input

Do not skip the final explanation. It is important for the researcher to verify your choices."""


def extract_thinking(text: str) -> tuple[str, str]:
    """Return (thinking_content, response_content) split from raw model output."""
    matches = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    thinking = "\n\n".join(m.strip() for m in matches)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    return thinking, cleaned


def list_models() -> list[str]:
    try:
        r = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def chat_with_tools(messages: list[dict], model: str, tools: list[dict]) -> dict:
    """Non-streaming single turn with tool support."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "tools": tools,
        "stream": False,
        "options": {"num_ctx": 8192},
    }
    try:
        r = httpx.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=180)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            pass
        raise RuntimeError(
            f"Ollama returned {e.response.status_code}. "
            f"Try restarting Ollama or pulling the model again.\nDetail: {body}"
        ) from e
    msg = r.json()["message"]
    raw = msg.get("content", "")
    thinking, cleaned = extract_thinking(raw)
    msg["content"] = cleaned if cleaned else raw
    msg["thinking"] = thinking
    return msg


def chat_stream(messages: list[dict], model: str) -> Iterator[str]:
    """Streaming chat without tools."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        "stream": True,
    }
    with httpx.stream("POST", f"{OLLAMA_BASE}/api/chat", json=payload, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            chunk = data.get("message", {}).get("content", "")
            if chunk:
                yield chunk
            if data.get("done"):
                break


def is_available() -> bool:
    try:
        httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2).raise_for_status()
        return True
    except Exception:
        return False
