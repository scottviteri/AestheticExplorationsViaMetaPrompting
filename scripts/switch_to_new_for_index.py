from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"


def strip_used_suffix(used: str) -> str:
    suffix = ", landscape composition, 3:2 aspect ratio, 4x6 inch print"
    if used.endswith(suffix):
        return used[: -len(suffix)].rstrip()
    return used.strip()


def find_prompt_dir_by_index(index: int) -> Path:
    pref = f"{index:03d}-"
    for child in sorted(PROMPTS_DIR.iterdir()):
        if child.is_dir() and child.name.startswith(pref):
            return child
    raise SystemExit(f"Prompt folder with index {index:03d} not found")


def choose_used_prompt_text(pdir: Path) -> str:
    # Prefer hyphen tag; select lexicographically last variant
    cands = sorted(pdir.glob("prompt_used-gptimage1-openai*.txt"))
    if not cands:
        raise SystemExit(f"No prompt_used-*.txt found in {pdir}")
    used_text = cands[-1].read_text(encoding="utf-8").strip()
    return strip_used_suffix(used_text)


def move_images(src_dir: Path, dst_dir: Path) -> int:
    moved = 0
    for p in sorted(src_dir.glob("front-gptimage1-openai*.png")):
        target = dst_dir / p.name
        try:
            # If target exists with same name, skip to avoid clobber
            if target.exists():
                continue
            p.replace(target)
            moved += 1
        except Exception:
            continue
    return moved


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Switch a prompt folder to use its NEW images and prompt")
    ap.add_argument("--index", type=int, required=True)
    args = ap.parse_args()

    pdir = find_prompt_dir_by_index(args.index)
    new_dir = pdir / "new_fronts"
    old_dir = pdir / "old_fronts"
    prompt_txt = pdir / "prompt.txt"

    if not new_dir.exists():
        raise SystemExit(f"No new_fronts/ in {pdir}")
    old_text = prompt_txt.read_text(encoding="utf-8").strip() if prompt_txt.exists() else ""
    new_text = choose_used_prompt_text(pdir)

    # Ensure subdirs and prompt snapshots
    new_dir.mkdir(exist_ok=True)
    old_dir.mkdir(exist_ok=True)
    (new_dir / "prompt.txt").write_text(new_text + "\n", encoding="utf-8")
    if old_text:
        (old_dir / "prompt.txt").write_text(old_text + "\n", encoding="utf-8")

    # Move current main images to old_fronts (skip if identical already exists)
    move_images(pdir, old_dir)
    # Move new images up to main
    moved_up = move_images(new_dir, pdir)

    # Replace active prompt with new text
    prompt_txt.write_text(new_text + "\n", encoding="utf-8")

    print(f"Switched {pdir.name} to NEW prompt/images ({moved_up} image(s) promoted)")


if __name__ == "__main__":
    main()


