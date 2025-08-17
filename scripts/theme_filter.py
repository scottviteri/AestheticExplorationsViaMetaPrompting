#!/usr/bin/env python3
"""
Filter conversations by theme to pick interesting, image-prompt-worthy entries.

Reads a source JSONL (default: GPTConversationAnalysis/themes/themes_per_conversation.jsonl)
and appends interesting entries to a target JSONL (default: GPTConversationAnalysis/themes/interesting_conversations.jsonl).

Decision logic
- If --use-model is set and OpenAI credentials are available, uses gpt-5-nano via structured outputs
  (single boolean field, strict schema, temperature 0) to decide interesting vs mundane.
- Otherwise falls back to a lightweight keyword heuristic.

Behavior
- Incremental and unique: does not duplicate existing IDs in the target file.
- Start/End slicing by 1-based index over the source file order.
"""

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Set, Optional
import os
import json as _json


REPO = Path(__file__).resolve().parents[1]
ANALYSIS = REPO / "GPTConversationAnalysis"
THEMES_DIR = ANALYSIS / "themes"
SRC_JSONL = THEMES_DIR / "themes_per_conversation.jsonl"
OUT_JSONL = THEMES_DIR / "interesting_conversations.jsonl"


NEGATIVE_KEYWORDS: Set[str] = {
    # Devices / logistics / support
    "ipad", "iphone", "android", "pixel", "ubreakifix", "appointment", "shipping", "logistics",
    "support", "help", "troubleshooting", "reset", "formatting",
    # Security / accounts / passcodes / telecom
    "security", "yubikey", "2fa", "two-step", "passcode", "webauthn", "fido2", "mfa",
    "account", "password", "google fi", "sim", "sim lock", "bootloader", "unlock", "number porting", "carrier", "telecom",
    # Printing / drivers / system setup
    "printer", "printing", "cups", "canon", "mg3620", "driver", "drivers", "airprint",
    # Networking / home devices
    "wifi", "wi-fi", "network", "ssid", "kasa", "camera",
    # Health / mundane personal care
    "health", "dermatitis", "scalp", "treatment", "itching", "battery", "swelling", "narcolepsy", "autoimmune", "alopecia", "bromhidrosis", "body odor", "medical research",
    # Cooking / food safety
    "cooking", "recipe", "artichoke", "fig", "food safety", "edible", "digestibility",
    # Household / event logistics / cleaning
    "wedding", "cake stand", "cleaning", "silver", "silver plate", "tarnish",
    # How-to software usage / CLI specifics / dev env setup
    "image editing", "opacity", "transparency", "graphic design", "feh", "image viewer", "zoom controls", "command line", "cli",
    "arch", "arch linux", "pacman", "setxkbmap", "xorg", "xorg-server", "systemd", "fbdev", "xf86-video-fbdev",
    "install", "installation", "package", "package manager",
    "mu4e", "git", "github", "clone", "refspec", "branching", "permissions", "collaborators",
    "nvidia", "va-api", "module", "module size", "hardware",
    "graphviz", "error",
    # Performance / stability / productivity tooling
    "cursor", "cursor lag", "performance", "performance issues", "stability", "workspace", "cache", "cache management",
    "tmux", "key binding", "shortcut", "shortcuts", "productivity", "session",
    # Remote/terminal protocols
    "ssh", "x11", "x11 forwarding", "scp", "sftp", "remote access", "terminal protocols", "file transfer",
    # Browsers / extensions / notebooks / scraping
    "firefox", "addon", "extension", "temporary installation", "jupyter", "notebook", "web scraping", "scraping", "python code",
    # Generic AI tool usage
    "dalle", "image generation", "ai art",
    # Academic admin / policies
    "paper submission", "desk rejection", "page limits", "conference policies", "academic guidelines",
    "email etiquette", "academic titles",
    # Household maintenance / pests / event linens
    "house maintenance", "pest control", "rodent", "mouse", "entry points", "apartment", "plumbing", "utilities", "home inspection",
    "table linens", "linen", "dimensions", "drop length", "event planning", "rectangular tables",
}


POSITIVE_KEYWORDS: Set[str] = {
    # Math aesthetics / geometry / topology
    "torus", "deltoid", "fractal", "mandelbrot", "julia", "sierpinski", "geometry", "topology",
    "category", "functor", "adjunction", "yoneda", "diagram", "string diagram", "hasse",
    "lambda", "combinator", "repl", "fixed point", "banach", "kleene",
    "manifold", "geodesic", "information geometry", "fisher", "curvature", "tensor",
    "clifford", "bivector", "rotor", "poincar", "conformal", "hyperbolic",
    "fiber bundle", "bundle", "atlas", "holonomy", "connection", "lattice", "ouroboros",
    "measure", "sigma-algebra", "σ-algebra", "set theory",
}


def record_is_interesting(themes: List[str]) -> bool:
    joined = " ".join(t.lower() for t in (themes or []))
    if not joined.strip():
        return False
    # Exclude if any negative keyword appears
    for neg in NEGATIVE_KEYWORDS:
        if neg in joined:
            return False
    # Include if any positive keyword appears
    for pos in POSITIVE_KEYWORDS:
        if pos in joined:
            return True
    # Otherwise, require at least two non-trivial themes as a weak signal
    nontrivial = [t for t in themes if len(t.strip()) >= 5]
    return len(nontrivial) >= 2 and any(ch.isalpha() for ch in joined)


# Smaller keyword subsets provided to the model as hints (not hard rules)
NEGATIVE_HINTS: List[str] = [
    "logistics", "shipping", "appointment", "printer", "drivers",
    "password", "passcode", "2fa", "yubikey", "wifi", "health", "treatment",
    "google fi", "sim lock", "bootloader", "number porting", "carrier",
    "cooking", "food safety", "artichoke", "fig",
    "wedding", "cleaning", "silver", "tarnish",
    "graphic design", "image editing", "feh", "image viewer", "command line",
    "arch linux", "pacman", "setxkbmap", "xorg", "systemd", "install", "package",
    "mu4e", "git", "github", "clone", "permissions",
    "nvidia", "va-api", "module",
    "graphviz", "error",
    "cursor", "performance", "stability", "workspace", "cache",
    "tmux", "key binding", "shortcuts", "productivity",
    "ssh", "x11", "scp", "sftp", "remote access",
    "firefox", "addon", "extension", "jupyter", "notebook", "web scraping",
    "dalle", "image generation", "ai art",
    "paper submission", "desk rejection", "page limits", "email etiquette", "academic titles",
    "house maintenance", "pest control", "rodent", "mouse", "plumbing", "utilities",
    "table linens", "linen", "event planning",
]

POSITIVE_HINTS: List[str] = [
    "torus", "fractal", "category theory", "lambda calculus", "manifold",
    "information geometry", "rotor", "holonomy", "hyperbolic", "conformal",
    "aesthetics", "metaphysics", "ethics", "ontology", "semantics", "philosophy",
    "cooperation", "wisdom", "self-reference", "ouroboros", "symmetry", "recursion", "fixed point", "ritual", "altar", "cathedral",
]


SYSTEM_MODEL_PROMPT = (
    "You are classifying whether a conversation's short theme tags indicate an interesting topic versus mundane.\n"
    "Interesting: unique ideas, abstractions, deep or novel concepts, aesthetics, philosophy, math/geometry,\n"
    "visually evocative seeds, or intellectually rich discussions.\n"
    "Mundane: logistics, how-to, troubleshooting, device setup/unlocking, security/account configuration,\n"
    "basic cooking or food safety, household cleaning/maintenance, wedding/event logistics, generic software/CLI usage,\n"
    "OS/configuration (e.g., Arch Linux, packages, drivers), diagnosing performance/stability or productivity tips (e.g., tmux shortcuts),\n"
    "remote access/protocols (SSH/X11/SCP), browser extensions, notebooks/scraping, git/admin,\n"
    "house maintenance/pest control, event linens/planning, and administrative/policy or etiquette questions.\n"
    "Default to mundane if uncertain or if tags are primarily tools, vendors, errors, or operational verbs.\n"
    "Use the hints as soft guidance; they are not exhaustive.\n"
    "Answer using a strict JSON schema with a single boolean field 'interesting'."
)


def model_is_interesting(themes: List[str], model: str = "gpt-5-nano") -> Optional[bool]:
    try:
        from openai import OpenAI
    except Exception:
        return None

    if not os.getenv("OPENAI_API_KEY"):
        return None

    client = OpenAI()

    # Prepare schema for strict structured outputs
    schema = {
        "name": "InterestingDecision",
        "schema": {
            "type": "object",
            "properties": {
                "interesting": {"type": "boolean"}
            },
            "required": ["interesting"],
            "additionalProperties": False,
        },
        "strict": True,
    }

    user_text = (
        "Theme tags: " + ", ".join(str(t) for t in themes) + "\n\n"
        + "Guidance (hints, not rules):\n"
        + "Positive cues: " + ", ".join(POSITIVE_HINTS) + "\n"
        + "Negative cues: " + ", ".join(NEGATIVE_HINTS) + "\n\n"
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
        data = _json.loads(content or "{}")
        val = data.get("interesting")
        if isinstance(val, bool):
            return val
        return None
    except Exception:
        # Fallback to None (caller can use heuristic)
        return None


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
    p = argparse.ArgumentParser(description="Filter interesting conversations into a separate JSONL")
    p.add_argument("--source", type=Path, default=SRC_JSONL, help="Source JSONL of themes per conversation")
    p.add_argument("--out", type=Path, default=OUT_JSONL, help="Target JSONL for interesting conversations")
    p.add_argument("--start", type=int, required=True, help="1-based start line in source JSONL")
    p.add_argument("--end", type=int, required=True, help="1-based end line in source JSONL (inclusive)")
    p.add_argument("--use-model", action="store_true", help="Use gpt-5-nano structured outputs to decide interest")
    p.add_argument("--model", type=str, default="gpt-5-nano", help="Model name for structured outputs decision")
    args = p.parse_args()

    if not args.source.exists():
        raise SystemExit(f"Source not found: {args.source}")

    existing_ids = load_existing_ids(args.out)

    # Read the specified slice from source
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
            decision: Optional[bool] = None
            if args.use_model:
                decision = model_is_interesting(themes, model=args.model)
            if decision is None:
                decision = record_is_interesting(themes)
            if not decision:
                continue
            outfh.write(json.dumps({"id": cid, "themes": themes}, ensure_ascii=False) + "\n")
            try:
                outfh.flush()
            except Exception:
                pass
            appended += 1
            existing_ids.add(str(cid))

    print(f"Appended {appended} interesting conversation(s) → {args.out}")


if __name__ == "__main__":
    main()


