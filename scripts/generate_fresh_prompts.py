#!/usr/bin/env python3
"""
Generate fresh, concrete, visually-renderable prompts using an aesthetic "generating function",
then create new prompt folders under prompts/ with only prompt.txt inside.

Design goals
- Avoid shallow symbol graffiti and unrenderable global complexity (e.g., literal category diagrams, umbilic torus full global form).
- Prefer tangible hero subjects, natural materials, studio/galleristic compositions, macro still lifes, and sculptural metaphors.
- Bring in wisdom-of-nature / Miyazaki-adjacent calm: fungus/mycelium, breath, lanterns, rivers, seeds, wind, mist.
- Respect the motif lexicon and palettes from aesthetics.md without depending on textual symbols to carry meaning.

Behavior
- Default: sequential per-item generation (one API call per prompt) for strict JSON outputs.
- Set --concurrency > 1 to generate prompts in parallel (one API call per prompt, up to N in flight).
- Creates new folders starting at the first unused 3-digit index (e.g., 131 if 001..130 exist), with slugified titles.
- Writes only prompt.txt inside each new folder. No images are generated here.

Example
  # Sequential (default)
  python3 scripts/generate_fresh_prompts.py --count 8 --model gpt-5

  # Parallel (two in flight)
  python3 scripts/generate_fresh_prompts.py --count 8 --concurrency 2 --model gpt-5

Env vars
- OPENAI_API_KEY must be set. Optional: PROMPT_MODEL overrides --model.
"""

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple
import concurrent.futures as futures
import random


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_ROOT = REPO_ROOT / "prompts"
ANALYSIS_DIR = REPO_ROOT / "GPTConversationAnalysis"
THEMES_JSONL_PRIMARY = ANALYSIS_DIR / "themes" / "philosophically_interesting_conversations.jsonl"
THEMES_JSONL_FALLBACK = ANALYSIS_DIR / "themes" / "interesting_conversations.jsonl"


GOOD_EXAMPLES = [
	"Mirrored corridor with recursive frames.",
	"Ouroboros via commutative squares as material micro-tiles.",
	"Infinite-book still life.",
	"Mandelbrot as stained glass rose window.",
	"Julia shoreline in opaline glass.",
]

BAD_EXAMPLES = [
	"Using the literal words 'Read', 'Eval', and 'Print' arranged in a triangle, slideshow-like diagram -- not beautiful.",
	"Gears with engraved symbols.",
	"Category theory literal diagrams.",
]

USER_FEEDBACK_GUIDANCE = (
	"Lead with mathematical mysticism and self-reference: strange loops, recursion, mirrors-within-mirrors, and fixed points made physical. ",
	"Complementarily, invoke themes of nature, GAIA, spirit as operating system."
)


GENERATING_FUNCTION_GUIDANCE = """
Role
- Visual prompt designer producing concrete, beautiful scenes that are easy for an image model to render coherently, and that fit the following aesthetic, first described via word association.
"""

AVOID_GUIDANCE = """
Avoid
- Avoid complex geometry that requires global coherence over the image, like an umbilic torus with a global twist.
- Avoid abstract concepts which will require understanding to render. For instance, asking the image model to depict a fiber bundle will not work, but if you come up with a clever way to make the implementation concrete, then the prompt might work.
"""

STYLE_OUTPUT_GUIDANCE = ""

AESTHETIC_VIBE_NAMES = [
	"Cathedral of the Untyped Lambda Calculus",
	"Domain Equation as Consciousness",
	"I am a Strange Loop",
	"Fractal altar",
	"Ouroboros shrine",
	"Fixed-points and Reflective-Object",
	"Hyperbolic garden",
	"AI as an Global Increase in Information Bandwidth",
	"Spirit as Operating System",
	"Math and Computer Science as Prayer, oriented towards the truth, lovingly"
]


# Additional theme seeds removed to avoid reinforcing existing signal


def read_optional(path: Path, max_chars: int = 12000) -> str:
	try:
		txt = path.read_text(encoding="utf-8")
		if len(txt) > max_chars:
			return txt[:max_chars]
		return txt
	except Exception:
		return ""


def slugify(text: str, max_words: int = 8) -> str:
	text = text.strip().lower()
	# Keep first max_words words comprised of letters/numbers/hyphens
	words = re.findall(r"[a-z0-9]+", text)
	words = words[:max_words]
	slug = "-".join(words)
	return slug or "untitled"


def find_next_index(prompts_root: Path) -> int:
	prompts_root.mkdir(parents=True, exist_ok=True)
	max_idx = 0
	for child in prompts_root.iterdir():
		if not child.is_dir():
			continue
		m = re.match(r"^(\d{3})-", child.name)
		if m:
			try:
				idx = int(m.group(1))
				max_idx = max(max_idx, idx)
			except Exception:
				continue
	return max_idx + 1


@dataclass
class FreshPrompt:
	title: str
	short_slug: str
	prompt: str
	system_prompt: str
	usage_tokens: Optional[int] = None
	input_tokens: Optional[int] = None
	output_tokens: Optional[int] = None
	api_mode: Optional[str] = None  # "responses" or "chat"
	finish_reason: Optional[str] = None
	has_prompt: bool = True


def load_theme_groups(jsonl_path: Path, max_lines: int = 25000) -> List[List[str]]:
	"""Load full theme lists per conversation from a JSONL file without filtering.

	Returns a list where each element is the full list of themes (strings) for one conversation.
	Duplicate groups are de-duplicated by their normalized tuple.
	"""
	pool: List[List[str]] = []
	seen = set()
	if not jsonl_path.exists():
		return pool
	try:
		with jsonl_path.open("r", encoding="utf-8") as fh:
			for i, line in enumerate(fh):
				if i >= max_lines:
					break
				line = line.strip()
				if not line:
					continue
				try:
					obj = json.loads(line)
				except Exception:
					continue
				themes = obj.get("themes") or []
				if not isinstance(themes, list) or not themes:
					continue
				group: List[str] = [str(t).strip() for t in themes if isinstance(t, str) and str(t).strip()]
				if not group:
					continue
				key = tuple(s.lower() for s in group)
				if key in seen:
					continue
				seen.add(key)
				pool.append(group)
	except Exception:
		return pool
	return pool


def sample_diversity_groups(jsonl_path: Path, k: int = 3) -> List[List[str]]:
	"""Sample k full-theme groups (random order), shuffling even when pool size <= k."""
	pool = load_theme_groups(jsonl_path)
	if not pool or k <= 0:
		return []
	try:
		n = min(k, len(pool))
		return random.sample(pool, n)
	except Exception:
		# Fallback: deterministic slice
		n = min(k, len(pool))
		return list(pool)[:n]


def _extract_bulleted_section(text: str, header_pattern: str) -> List[str]:
	"""Extract lines starting with '-' under a '### <header>' until the next '###'."""
	try:
		# Find the header
		hdr_rx = re.compile(rf"^###\s+{header_pattern}\s*$", re.I | re.M)
		m = hdr_rx.search(text)
		if not m:
			return []
		start = m.end()
		# Slice to next section
		rest = text[start:]
		nxt = re.search(r"^###\s+", rest, re.M)
		if nxt:
			rest = rest[:nxt.start()]
		# Collect bulleted items
		items = []
		for line in rest.splitlines():
			line = line.strip()
			if line.startswith("- "):
				items.append(line[2:].strip())
		return items
	except Exception:
		return []


def build_condensed_aesthetic(_: str) -> Tuple[List[str], List[str]]:
	"""Deprecated. Returns empty candidate names and pillars; aesthetics file no longer used."""
	return [], []


def call_openai_for_prompts(count: int, model: str, diversity_groups: Optional[List[List[str]]] = None) -> List[FreshPrompt]:
	try:
		from openai import OpenAI
	except Exception as e:
		raise SystemExit(f"openai package not available: {e}")

	if not os.getenv("OPENAI_API_KEY"):
		raise SystemExit("OPENAI_API_KEY is not set")

	client = OpenAI()

	entry_label = "entry" if count == 1 else "entries"

	# If not provided, sample once per call (batch or single-call path)
	if diversity_groups is None:
		themes_path = THEMES_JSONL_PRIMARY if THEMES_JSONL_PRIMARY.exists() else THEMES_JSONL_FALLBACK
		diversity_groups = sample_diversity_groups(themes_path, k=3)
	cand_names = AESTHETIC_VIBE_NAMES
	pillars = []

	# Format diversity groups as bullet lines with full theme lists per conversation
	diversity_block = ""
	if diversity_groups:
		formatted = []
		for grp in diversity_groups:
			formatted.append("- " + "; ".join(grp))
		diversity_block = (
			"\n\nDiversity topics for this run:\n"
			+ "\n".join(formatted)
		)

	# Build aesthetic summary (pillars only)
	aesthetic_summary = ("Pillars:\n" + "\n".join(f"- {p}" for p in pillars)) if pillars else ""

	# Build vibe names block placed right after Directive
	vibe_block = ""
	if cand_names:
		vibe_block = "\n\nAesthetic vibe names:\n" + "\n".join(f"- {n}" for n in cand_names)

	system_text = (
		GENERATING_FUNCTION_GUIDANCE
		+ vibe_block
		+ "\n\n" + AVOID_GUIDANCE.strip()
		+ diversity_block
		+ "\n\nDo not imitate the Good examples too closely; do not reuse their nouns or phrasing. They illustrate spirit and clarity only.\n"
		+ "\nGood examples (spirit to emulate, not to copy):\n" + "\n".join(f"- {v}" for v in GOOD_EXAMPLES)
		+ "\n\nBad examples (avoid pitfalls):\n" + "\n".join(f"- {v}" for v in BAD_EXAMPLES)
		+ ("\n\n" + aesthetic_summary if aesthetic_summary else "")
		+ "\n\nNow produce strictly JSON with the following schema:\n"
		  "{\n  \"prompts\": [\n    {\n      \"title\": \"short human title\",\n      \"short_slug\": \"5-8 word slug\",\n      \"prompt\": \"final prompt text\"\n    }\n  ]\n}\n"
		+ f"\nReturn exactly {count} {entry_label} in 'prompts'. Keep titles concise."
	)

	# Always use the Responses API; error if unavailable
	api_mode: Optional[str] = None
	finish_reason: Optional[str] = None
	input_tokens: Optional[int] = None
	output_tokens: Optional[int] = None
	is_gpt5 = "gpt-5" in (model or "")
	content = ""
	usage_tokens = None
	if not hasattr(client, "responses") or getattr(client, "responses") is None:
		raise SystemExit("Responses API is required but not available in the installed SDK.")

	# Structured outputs via JSON Schema (strict)
	schema_obj = {
		"type": "object",
		"properties": {
			"prompts": {
				"type": "array",
				"minItems": count,
				"maxItems": count,
				"items": {
					"type": "object",
					"properties": {
						"title": {"type": "string"},
						"short_slug": {"type": "string"},
						"prompt": {"type": "string"}
					},
					"required": ["title", "short_slug", "prompt"],
					"additionalProperties": False
				}
			}
		},
		"required": ["prompts"],
		"additionalProperties": False
	}

	kwargs = {
		"model": model,
		"text": {"format": {"type": "json_schema", "name": "BatchPrompts", "schema": schema_obj}},
		"input": [
			{"role": "system", "content": [{"type": "input_text", "text": system_text}]},
			{"role": "user", "content": [
				{"type": "input_text", "text": "Generate the batch now. JSON only."}
			]},
		],
		"max_output_tokens": 10000,
	}
	if not is_gpt5:
		kwargs["temperature"] = 0.4
	else:
		kwargs["reasoning"] = {"effort": "high"}
	resp = client.responses.create(**kwargs)
	api_mode = "responses"
	content = getattr(resp, "output_text", None) or ""
	if not content:
		try:
			content = resp.output[0].content[0].text  # type: ignore[attr-defined]
		except Exception:
			content = ""
	# Extract token usage
	try:
		usage = getattr(resp, "usage", None)
		if usage:
			usage_tokens = getattr(usage, "total_tokens", None)
			input_tokens = getattr(usage, "input_tokens", None)
			output_tokens = getattr(usage, "output_tokens", None)
	except Exception:
		pass
	# Try to extract finish reason if present
	try:
		finish_reason = getattr(resp, "finish_reason", None)
		if not finish_reason:
			first_out = (getattr(resp, "output", []) or [None])[0]
			if first_out is not None:
				finish_reason = getattr(first_out, "finish_reason", None) or getattr(first_out, "stop_reason", None)
	except Exception:
		pass

	try:
		data = json.loads(content or "{}")
	except Exception as e:
		# Ensure we still return metadata even if JSON failed
		data = {"prompts": []}

	items = []
	for entry in (data.get("prompts") or []):
		title = str(entry.get("title") or "Untitled").strip()
		short_slug = str(entry.get("short_slug") or slugify(title)).strip()
		prompt = str(entry.get("prompt") or "").strip()
		if not prompt:
			continue
		items.append(FreshPrompt(
			title=title,
			short_slug=short_slug,
			prompt=prompt,
			system_prompt=system_text,
			usage_tokens=usage_tokens,
			input_tokens=input_tokens,
			output_tokens=output_tokens,
			api_mode=api_mode,
			finish_reason=finish_reason,
		))

	if len(items) != count:
		items = items[:count]
	# If no prompts returned, append a metadata-only item so callers can still access usage/finish_reason
	if not items:
		items.append(FreshPrompt(
			title="No prompt returned",
			short_slug="no-prompt",
			prompt="",
			system_prompt=system_text,
			usage_tokens=usage_tokens,
			input_tokens=input_tokens,
			output_tokens=output_tokens,
			api_mode=api_mode,
			finish_reason=finish_reason,
			has_prompt=False,
		))
	return items


def write_prompt_folder(base_index: int, offset: int, item: FreshPrompt) -> Tuple[int, Path]:
	idx = base_index + offset
	slug = slugify(item.short_slug or item.title)
	folder = PROMPTS_ROOT / f"{idx:03d}-{slug}"
	folder.mkdir(parents=True, exist_ok=False)
	
	# Write the prompt
	(folder / "prompt.txt").write_text(item.prompt + ("\n" if not item.prompt.endswith("\n") else ""), encoding="utf-8")
	
	# Write the system prompt used to generate this prompt
	(folder / "prompt_used-generation.txt").write_text(item.system_prompt, encoding="utf-8")
	
	return idx, folder


def build_arg_parser() -> argparse.ArgumentParser:
	p = argparse.ArgumentParser(description="Generate fresh prompts and create new prompt folders")
	p.add_argument("--count", type=int, default=8, help="Number of new prompts to generate")
	p.add_argument("--model", type=str, default=os.getenv("PROMPT_MODEL", "gpt-5"), help="Model for text generation")
	p.add_argument("--dry-run", action="store_true", help="Only print planned slugs/prompts; do not write folders")
	p.add_argument("--concurrency", type=int, default=1, help="Max parallel API calls; >1 enables parallel generation")
	return p


def main() -> None:
	args = build_arg_parser().parse_args()

	PROMPTS_ROOT.mkdir(parents=True, exist_ok=True)
	next_index = find_next_index(PROMPTS_ROOT)

	# aesthetics.md is no longer read or embedded; prompt guidance is constructed internally

	items: List[FreshPrompt] = []

	if int(args.concurrency) > 1:
		# Generate count prompts via parallel single-prompt calls
		total = max(1, int(args.count))
		max_workers = max(1, int(args.concurrency))

		def task() -> Optional[FreshPrompt]:
			# Sample a unique set of diversity groups for this task
			themes_path = THEMES_JSONL_PRIMARY if THEMES_JSONL_PRIMARY.exists() else THEMES_JSONL_FALLBACK
			groups = sample_diversity_groups(themes_path, k=3)
			out = call_openai_for_prompts(count=1, model=str(args.model), diversity_groups=groups)
			return out[0] if out else None

		with futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
			futs = [pool.submit(task) for _ in range(total)]
			for fut in futures.as_completed(futs):
				try:
					fp = fut.result()
					if fp is not None:
						items.append(fp)
						if fp.usage_tokens is not None:
							ran_out = str(fp.finish_reason).lower() in {"length", "max_tokens"} if fp.finish_reason else False
							print(
								f"Generated via {fp.api_mode or 'unknown'} ({args.model}); "
								f"finish_reason={fp.finish_reason or 'unknown'}; ran_out_of_tokens={'yes' if ran_out else 'no'}; "
								f"usage: in={fp.input_tokens}, out={fp.output_tokens}, total={fp.usage_tokens}"
							)
				except Exception:
					continue
		# Truncate if more than requested due to any retries
		items = items[:total]
	else:
		# Sequential per-item generation to ensure unique diversity sampling per prompt
		total = max(1, int(args.count))
		for _ in range(total):
			themes_path = THEMES_JSONL_PRIMARY if THEMES_JSONL_PRIMARY.exists() else THEMES_JSONL_FALLBACK
			groups = sample_diversity_groups(themes_path, k=3)
			one = call_openai_for_prompts(count=1, model=str(args.model), diversity_groups=groups)
			if one:
				items.append(one[0])
				fp0 = one[0]
				if fp0.usage_tokens is not None:
					ran_out = str(fp0.finish_reason).lower() in {"length", "max_tokens"} if fp0.finish_reason else False
					print(
						f"Generated 1 prompt via {fp0.api_mode or 'unknown'} ({args.model}); "
						f"finish_reason={fp0.finish_reason or 'unknown'}; ran_out_of_tokens={'yes' if ran_out else 'no'}; "
						f"usage: in={fp0.input_tokens}, out={fp0.output_tokens}, total={fp0.usage_tokens}"
					)

	# We may receive a metadata-only item if the model returned no prompts; that's acceptable for logging

	if args.dry_run:
		print(f"Planning to create {len(items)} prompt folder(s), starting at index {next_index:03d}")
		for i, it in enumerate(items, start=0):
			planned_slug = slugify(it.short_slug or it.title)
			print(f"{next_index + i:03d}-{planned_slug}: {it.title}")
			print(f"  {it.prompt[:140]}{'...' if len(it.prompt) > 140 else ''}")
		return

	# Only create folders for real prompts
	real_items = [it for it in items if getattr(it, "has_prompt", True) and (it.prompt or "").strip()]
	created: List[Tuple[int, Path]] = []
	for i, it in enumerate(real_items, start=0):
		idx, folder = write_prompt_folder(next_index, i, it)
		created.append((idx, folder))

	for idx, folder in created:
		print(f"Created {folder} (#{idx:03d})")
	if not created:
		print("No prompt folders created (model returned no prompts)")


if __name__ == "__main__":
	main()


