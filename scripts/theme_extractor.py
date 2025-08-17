#!/usr/bin/env python3
"""
Minimal theme extraction over a slice of conversations with parallelism.

- Produces ONLY a few short themes (no summary) to minimize tokens
- Uses OpenAI prompt caching (KV cache) for stable rule/system segments
- Logs raw completions on JSON parse errors for debugging
- Append-only JSONL: cumulative across runs; skips existing IDs
- Parallel calls controlled by --concurrency; writes each record as soon as available

Usage examples:
  python scripts/theme_extractor.py --start 1 --end 10 --concurrency 3
"""

import argparse
import concurrent.futures as futures
import json
import hashlib
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Union


REPO = Path(__file__).resolve().parents[1]
PERSONAL = REPO / "PersonalDocuments"
ANALYSIS = REPO / "GPTConversationAnalysis"
CONV_PATH = PERSONAL / "conversations.json"

OUT_DIR = ANALYSIS / "themes"
OUT_JSONL = OUT_DIR / "themes_per_conversation.jsonl"
OUT_ROLLUP = OUT_DIR / "themes_rollup.md"
OUT_DEBUG = OUT_DIR / "raw_completion_errors.jsonl"

# Keep transcripts short to reduce tokens
TRANSCRIPT_MAX_CHARS = 2000

SYSTEM_PROMPT = (
    "You are a concise tagger. Extract 3–7 very short theme tags (1–3 words each) that capture the main topics. "
    "Return strict JSON: {\"themes\":[\"tag1\",\"tag2\",...]} — no other keys, no summary, no extra text."
)

USER_PROMPT_HEADER = "Transcript follows. Return ONLY JSON with a 'themes' array.\n\nTRANSCRIPT:\n"


def load_conversations() -> List[Dict[str, Any]]:
    data = json.loads(CONV_PATH.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "conversations" in data:
        return data["conversations"]
    if isinstance(data, list):
        return data
    raise SystemExit("Unsupported conversations.json structure")


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                txt = item.get("text") or item.get("value") or ""
                if not txt and "parts" in item and isinstance(item["parts"], list):
                    parts.append(" ".join(str(p) for p in item["parts"]))
                elif txt:
                    parts.append(str(txt))
        return " ".join(p for p in parts if p)
    if isinstance(content, dict):
        if "parts" in content and isinstance(content["parts"], list):
            return " ".join(str(p) for p in content["parts"]) or content.get("text", "")
        return content.get("text") or content.get("content") or json.dumps(content, ensure_ascii=False)
    return str(content)


def messages_to_text(messages_like: Union[List[Any], Dict[str, Any], str], max_chars: int) -> str:
    if isinstance(messages_like, dict) and "messages" in messages_like:
        entries = messages_like["messages"]
    elif isinstance(messages_like, list):
        entries = messages_like
    else:
        entries = [messages_like]

    parts: List[str] = []
    for m in entries:
        if isinstance(m, str):
            parts.append(m)
            continue
        if isinstance(m, dict):
            role = m.get("role") or m.get("speaker") or ""
            content = _stringify_content(m.get("content") or m.get("text"))
            parts.append(f"{role}: {content}" if role else content)
            continue
        parts.append(str(m))

    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def extract_transcript_from_conversation(conv: Dict[str, Any], max_chars: int) -> str:
    if "messages" in conv or "history" in conv:
        source = conv.get("messages") or conv.get("history")
        return messages_to_text(source, max_chars=max_chars)
    mapping = conv.get("mapping")
    if isinstance(mapping, dict):
        lines: List[str] = []
        for node in mapping.values():
            msg = node.get("message") if isinstance(node, dict) else None
            if not isinstance(msg, dict):
                continue
            author = msg.get("author", {})
            role = author.get("role") or author.get("name") or ""
            content = msg.get("content")
            text = _stringify_content(content)
            if not text and isinstance(msg.get("content"), dict):
                text = _stringify_content(msg["content"])
            if text:
                lines.append(f"{role}: {text}" if role else text)
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[:max_chars]
        return text
    return messages_to_text(conv, max_chars=max_chars)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def analyze_themes_minimal(transcript: str, *, conv_id: str, debug_log_path: Path) -> List[str]:
    """Call OpenAI with prompt caching and robust JSON parsing with logging."""
    from openai import OpenAI

    client = OpenAI()
    model = os.getenv("THEME_MODEL", "gpt-4o-mini")

    # Prefer Responses API for KV prompt caching
    content: str = ""
    try:
        resp = client.responses.create(
            model=model,
            response_format={"type": "json_object"},
            max_output_tokens=80,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": USER_PROMPT_HEADER,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "input_text",
                            "text": transcript,
                        },
                    ],
                },
            ],
        )
        content = getattr(resp, "output_text", None) or ""
        if not content:
            try:
                content = resp.output[0].content[0].text  # type: ignore[attr-defined]
            except Exception:
                content = ""
    except Exception:
        # Fallback to Chat Completions if Responses API is unavailable
        resp2 = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_HEADER + transcript},
            ],
            max_completion_tokens=80,
        )
        content = resp2.choices[0].message.content  # type: ignore[attr-defined]

    try:
        data = json.loads(content or "{}")
        themes = data.get("themes", [])
        themes = [str(t).strip()[:40] for t in themes if str(t).strip()]
        return themes[:7]
    except Exception:
        # Log raw content for debugging
        try:
            debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with debug_log_path.open("a", encoding="utf-8") as dbg:
                dbg.write(
                    json.dumps(
                        {
                            "id": conv_id,
                            "raw": content,
                            "transcript_sha256": _hash_text(transcript),
                            "transcript_excerpt": transcript[:400],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel minimal theme extraction over conversation range")
    parser.add_argument("--start", type=int, required=True, help="1-based start index")
    parser.add_argument("--end", type=int, required=True, help="1-based end index inclusive")
    parser.add_argument("--concurrency", type=int, default=1, help="Max concurrent OpenAI calls")
    args = parser.parse_args()

    convs = load_conversations()
    n = len(convs)
    s = max(1, args.start)
    e = min(args.end, n)
    if s > e:
        raise SystemExit("--start must be <= --end")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing conversation IDs to keep JSONL cumulative
    existing_ids = set()
    if OUT_JSONL.exists():
        with OUT_JSONL.open("r", encoding="utf-8") as jin:
            for line in jin:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cid0 = rec.get("id")
                    if cid0:
                        existing_ids.add(str(cid0))
                except Exception:
                    continue

    # Prepare work items
    work_indices = list(range(s - 1, e))

    # Shared output resources
    write_lock = threading.Lock()
    appended = 0

    # Open file handle once for incremental appends
    with OUT_JSONL.open("a", encoding="utf-8") as jout:
        def write_record(cid: str, themes: List[str]) -> None:
            nonlocal appended
            with write_lock:
                if cid in existing_ids:
                    return
                jout.write(json.dumps({"id": cid, "themes": themes}, ensure_ascii=False) + "\n")
                try:
                    jout.flush()
                    os.fsync(jout.fileno())
                except Exception:
                    pass
                existing_ids.add(cid)
                appended += 1

        def task_fn(idx: int) -> None:
            conv = convs[idx]
            cid = conv.get("id") or conv.get("conversation_id") or f"conv-{idx+1:05d}"
            if cid in existing_ids:
                return
            transcript = extract_transcript_from_conversation(conv, max_chars=TRANSCRIPT_MAX_CHARS)
            themes: List[str] = [] if not transcript.strip() else analyze_themes_minimal(transcript, conv_id=str(cid), debug_log_path=OUT_DEBUG)
            write_record(str(cid), themes)

        inflight: dict[futures.Future, int] = {}
        it = iter(work_indices)

        with futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            # Pre-fill
            while len(inflight) < max(1, args.concurrency):
                try:
                    i = next(it)
                except StopIteration:
                    break
                fut = pool.submit(task_fn, i)
                inflight[fut] = i

            # Keep submitting as tasks finish
            while inflight:
                done, _ = futures.wait(list(inflight.keys()), return_when=futures.FIRST_COMPLETED)
                for f in done:
                    inflight.pop(f, None)
                    try:
                        f.result()
                    except Exception:
                        pass
                    try:
                        i = next(it)
                        nf = pool.submit(task_fn, i)
                        inflight[nf] = i
                    except StopIteration:
                        pass

    # Recompute rollup from all JSONL entries
    unique_themes = set()
    if OUT_JSONL.exists():
        with OUT_JSONL.open("r", encoding="utf-8") as jin:
            for line in jin:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    for t in rec.get("themes", []) or []:
                        if str(t).strip():
                            unique_themes.add(str(t).strip())
                except Exception:
                    continue

    with OUT_ROLLUP.open("w", encoding="utf-8") as md:
        md.write("# Conversation Themes Rollup (parallel)\n\n")
        for t in sorted(unique_themes):
            md.write(f"- {t}\n")

    print(f"Appended {appended} new conversation(s). Wrote {OUT_ROLLUP}")


if __name__ == "__main__":
    main()


