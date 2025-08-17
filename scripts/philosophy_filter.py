#!/usr/bin/env python3
"""
Filter an already-interesting conversations JSONL down to those that are
"philosophically interesting" using gpt-5-nano with structured outputs.

Input (default): GPTConversationAnalysis/themes/interesting_conversations.jsonl
Output (default): GPTConversationAnalysis/themes/philosophically_interesting_conversations.jsonl

- Unique, incremental appends; no duplicates by ID
- Start/End slicing by 1-based line numbers over the source file
"""

import argparse
import json
from pathlib import Path
from typing import List, Optional, Set
import os


REPO = Path(__file__).resolve().parents[1]
ANALYSIS = REPO / "GPTConversationAnalysis"
THEMES_DIR = ANALYSIS / "themes"
SRC_JSONL = THEMES_DIR / "interesting_conversations.jsonl"
OUT_JSONL = THEMES_DIR / "philosophically_interesting_conversations.jsonl"


# Positive signals for fallbacks/heuristics (used if model unavailable)
POSITIVE_PHIL_HINTS: List[str] = [
	"philosophy", "philosophical", "metaphysics", "ontology", "epistemology", "ethics",
	"aesthetics", "meaning", "semantics", "logic", "agency", "consciousness", "mind",
	"values", "morality", "wisdom", "teleology", "free will", "personhood", "normative",
]

# Negative signals (strong mundane/ops/filtering topics)
NEGATIVE_OPS_HINTS: List[str] = [
	"printer", "drivers", "wifi", "account", "password", "2fa", "yubikey", "shipment",
	"logistics", "troubleshooting", "arch linux", "pacman", "install", "package", "error",
	"git", "github", "ssh", "x11", "scp", "sftp", "firefox", "extension", "notebook",
	"web scraping", "cursor", "performance", "stability", "tmux", "shortcut", "cooking",
	"food safety", "wedding", "cleaning", "tarnish", "house maintenance", "pest control",
]


SYSTEM_MODEL_PROMPT = (
	"Decide if a conversation described by short theme tags is philosophically interesting.\n"
	"Philosophically interesting = engages questions of meaning, knowledge, mind, values,\n"
	"ethics, metaphysics, ontology, epistemology, aesthetics, logic, agency, consciousness,\n"
	"semantics, or deep reflective themes (e.g., alignment ethics, wisdom pacing).\n"
	"Mundane/logistical topics (device setup, drivers, packages, generic troubleshooting,\n"
	"event logistics) are not philosophically interesting. When in doubt, return false.\n"
	"Answer with strict JSON schema containing one boolean field 'philosophically_interesting'."
)


def model_is_philosophically_interesting(themes: List[str], model: str = "gpt-5-nano") -> Optional[bool]:
	try:
		from openai import OpenAI
	except Exception:
		return None

	if not os.getenv("OPENAI_API_KEY"):
		return None

	client = OpenAI()

	# Strict structured outputs schema
	schema = {
		"name": "PhilosophyDecision",
		"schema": {
			"type": "object",
			"properties": {
				"philosophically_interesting": {"type": "boolean"}
			},
			"required": ["philosophically_interesting"],
			"additionalProperties": False,
		},
		"strict": True,
	}

	user_text = (
		"Theme tags: " + ", ".join(str(t) for t in themes) + "\n\n"
		+ "Return JSON only."
	)

	try:
		resp = client.responses.create(
			model=model,
			input=[
				{
					"role": "system",
					"content": [
						{"type": "input_text", "text": SYSTEM_MODEL_PROMPT, "cache_control": {"type": "ephemeral"}},
					],
				},
				{
					"role": "user",
					"content": [
						{"type": "input_text", "text": user_text},
					],
				},
			],
			response_format={
				"type": "json_schema",
				"json_schema": schema,
			},
			temperature=0,
			max_output_tokens=10,
		)
		content = getattr(resp, "output_text", None) or ""
		if not content:
			try:
				content = resp.output[0].content[0].text  # type: ignore[attr-defined]
			except Exception:
				content = ""
		data = json.loads(content or "{}")
		val = data.get("philosophically_interesting")
		if isinstance(val, bool):
			return val
		return None
	except Exception:
		return None


def heuristic_is_philosophically_interesting(themes: List[str]) -> bool:
	joined = " ".join(t.lower() for t in (themes or []))
	if not joined.strip():
		return False
	if any(neg in joined for neg in NEGATIVE_OPS_HINTS):
		return False
	return any(pos in joined for pos in POSITIVE_PHIL_HINTS)


def load_existing_ids(path: Path) -> Set[str]:
	ids: Set[str] = set()
	if not path.exists():
		return ids
	with path.open("r", encoding="utf-8") as fh:
		for line in fh:
			line = line.strip()
			if not line:
				continue
			try:
				rec = json.loads(line)
				cid = rec.get("id")
				if cid:
					ids.add(str(cid))
			except Exception:
				continue
	return ids


def main() -> None:
	p = argparse.ArgumentParser(description="Filter philosophically interesting conversations into a separate JSONL")
	p.add_argument("--source", type=Path, default=SRC_JSONL, help="Source JSONL of interesting conversations")
	p.add_argument("--out", type=Path, default=OUT_JSONL, help="Target JSONL for philosophically interesting conversations")
	p.add_argument("--start", type=int, required=True, help="1-based start line in source JSONL")
	p.add_argument("--end", type=int, required=True, help="1-based end line in source JSONL (inclusive)")
	p.add_argument("--model", type=str, default="gpt-5-nano", help="Model name for structured outputs decision")
	args = p.parse_args()

	if not args.source.exists():
		raise SystemExit(f"Source not found: {args.source}")

	existing_ids = load_existing_ids(args.out)

	# Read selected slice
	selected: List[dict] = []
	with args.source.open("r", encoding="utf-8") as fh:
		for idx, line in enumerate(fh, start=1):
			if idx < args.start:
				continue
			if idx > args.end:
				break
			line = line.strip()
			if not line:
				continue
			try:
				rec = json.loads(line)
				selected.append(rec)
			except Exception:
				continue

	appended = 0
	args.out.parent.mkdir(parents=True, exist_ok=True)
	with args.out.open("a", encoding="utf-8") as outfh:
		for rec in selected:
			cid = rec.get("id")
			themes = rec.get("themes") or []
			if not cid or cid in existing_ids:
				continue
			if not isinstance(themes, list):
				continue
			decision: Optional[bool] = model_is_philosophically_interesting(themes, model=args.model)
			if decision is None:
				decision = heuristic_is_philosophically_interesting(themes)
			if not decision:
				continue
			outfh.write(json.dumps({"id": cid, "themes": themes}, ensure_ascii=False) + "\n")
			try:
				outfh.flush()
			except Exception:
				pass
			appended += 1
			existing_ids.add(str(cid))

	print(f"Appended {appended} philosophically interesting conversation(s) → {args.out}")


if __name__ == "__main__":
	main()



