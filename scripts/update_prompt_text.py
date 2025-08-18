from __future__ import annotations

from pathlib import Path
import re
import argparse


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = REPO_ROOT / "prompts"


def find_prompt_dir_by_index(index: int) -> Path:
    pref = f"{index:03d}-"
    for child in sorted(PROMPTS_DIR.iterdir()):
        if child.is_dir() and child.name.startswith(pref):
            return child
    raise SystemExit(f"Prompt folder with index {index:03d} not found")


def main() -> None:
    ap = argparse.ArgumentParser(description="Update prompt.txt for a given index")
    ap.add_argument("--index", type=int, required=True)
    ap.add_argument("--text", type=str, required=True, help="New prompt text (use shell quotes)")
    args = ap.parse_args()

    pdir = find_prompt_dir_by_index(args.index)
    ptxt = pdir / "prompt.txt"
    ptxt.write_text(args.text.strip() + "\n", encoding="utf-8")
    # Also snapshot into any new_fronts/ or old_fronts/ if present
    for sub in ("new_fronts", "old_fronts"):
        sd = pdir / sub
        if sd.exists():
            (sd / "prompt.txt").write_text(args.text.strip() + "\n", encoding="utf-8")
    print(f"Updated {ptxt} and snapshots.")


if __name__ == "__main__":
    main()


