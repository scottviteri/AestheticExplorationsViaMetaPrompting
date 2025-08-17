#!/usr/bin/env python3
"""
Condense numbering of prompt folders under prompts/ to be contiguous, preserving order.

Behavior
- Finds directories matching NNN-slug under prompts/
- Sorts by existing NNN ascending (stable by name)
- Renames them to 001, 002, ..., keeping the original slug text
- Two-phase rename via unique temporary names to avoid collisions
- Supports --dry-run to show planned changes without modifying disk

Usage
  python3 scripts/condense_prompt_numbers.py            # perform renumber
  python3 scripts/condense_prompt_numbers.py --dry-run  # preview only
"""

import argparse
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_ROOT = REPO_ROOT / "prompts"


@dataclass
class PromptFolder:
    index: int
    slug: str
    path: Path


def list_prompt_folders(root: Path) -> List[PromptFolder]:
    items: List[PromptFolder] = []
    if not root.exists():
        return items
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        m = re.match(r"^(\d{3})-(.+)$", child.name)
        if not m:
            continue
        try:
            idx = int(m.group(1))
        except Exception:
            continue
        slug = m.group(2)
        items.append(PromptFolder(index=idx, slug=slug, path=child))
    # Stable sort by index then name to preserve order for equal indices
    items.sort(key=lambda pf: (pf.index, pf.path.name))
    return items


def build_new_names(items: List[PromptFolder]) -> List[Tuple[Path, Path]]:
    mappings: List[Tuple[Path, Path]] = []
    for new_idx, it in enumerate(items, start=1):
        new_name = f"{new_idx:03d}-{it.slug}"
        new_path = it.path.with_name(new_name)
        if new_path == it.path:
            continue
        mappings.append((it.path, new_path))
    return mappings


def perform_two_phase_rename(mappings: List[Tuple[Path, Path]], *, dry_run: bool = False) -> None:
    if not mappings:
        print("No changes needed.")
        return

    # Phase 1: rename all sources to unique temporary names
    temp_pairs: List[Tuple[Path, Path]] = []
    for src, _ in mappings:
        tmp = src.with_name(f"__renum_tmp_{uuid.uuid4().hex}_{src.name}")
        temp_pairs.append((src, tmp))

    if dry_run:
        for (src, dst_tmp), (_, final) in zip(temp_pairs, mappings):
            print(f"PLAN: {src.name} -> {final.name}")
        return

    # Execute phase 1
    for src, tmp in temp_pairs:
        if not src.exists():
            continue
        src.rename(tmp)

    # Phase 2: rename each temp to its final destination
    for (_, tmp), (_, final) in zip(temp_pairs, mappings):
        # Ensure destination parent exists
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp.rename(final)

    print(f"Renamed {len(mappings)} folder(s) to contiguous numbering.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Condense prompt folder numbering to contiguous sequence")
    ap.add_argument("--dry-run", action="store_true", help="Show planned renames without applying them")
    args = ap.parse_args()

    if not PROMPTS_ROOT.exists():
        print(f"prompts/ not found at {PROMPTS_ROOT}", file=sys.stderr)
        raise SystemExit(1)

    items = list_prompt_folders(PROMPTS_ROOT)
    if not items:
        print("No prompt folders found matching NNN-slug.")
        return

    mappings = build_new_names(items)
    perform_two_phase_rename(mappings, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    main()


