#!/usr/bin/env python3
"""
Populate prompt_used-generation.txt for groups of prompt folders after renumbering,
using the actual conversation instructions provided by the user for each batch of 12.

Groups (renumbered, contiguous)
- 054–065 → 1st 12
- 066–077 → 2nd 12
- 078–089 → 3rd 12
- 090–101 → 4th 12
- 102–113 → 5th 12

Usage
  python3 scripts/add_meta_prompts.py            # write missing files only
  python3 scripts/add_meta_prompts.py --force    # overwrite existing
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "prompts"


META_1ST_12 = (
    "Would you mind creating a file with suggestions of next image prompts, by looking at some example prompts in the prompts folder, and mixing random topics from philosophically_interesting_conversations.jsonl into prompts. Maybe emphasize combinations which are amenable to interesting visualization. I like the aesthetics of generate_fresh_prompts but they are lacking diversity.\n\n"
    "Then please create folders for each of those prompts as ./prompts/your_prompt/prompt.txt.\n\n"
    "Thanks!\n"
)


META_2ND_12 = (
    "This was pretty good!\n"
    "Could you make more such prompts and corresponding folders, but this time try harder to creatively engage with the corresponding content from philosophically_interesting_conversations.jsonl?\n"
    "It is ok if you selectively pick topics (or mixtures of topics!) from the jsonl such that you can think of ways to depict the core idea in a load bearing fashion\n"
)


META_3RD_12 = (
    "Ok, this last batch was even better.\n"
    "I will ask you to do one last round of the same. Please keep up the good work, giving attention and care into each one (or simultaneous pair) of these unique philosophical topics and their beautiful visualization.\n"
    "Thank You!\n"
)


META_4TH_12 = (
    "Ok, this time I will ask to create prompts in a bit of a different way.\n"
    "I am just going to look through the images we have so far and point out some themes that I would like to see more of.\n\n"
    "I like things that are fractal related and I want to see more raw fractal texture, like one might see in a video of traveling through a mandlebulb universe\n"
    "Visualizations of alien universes with different physics where those differences can be described mathematically but it is up to you (or the image model) to visualize given that description \n"
    "Game of life aesthetics -- gliders and building complexity from simplicity\n"
    "I liked the chladni plate-like patterns of watter in the graph laplacian water harp prompt, and I would love to see more interesting spectral dynamics and arrangements of water physics \n"
    "More various different kinds of curious mathematical famous objects that are amenable to visualization -- such as those listed on the page @https://en.wikipedia.org/wiki/List_of_topologies \n"
    "  (eg sierpinski carpet triangle cantor koch snowflake menger sponge hawaiian earing space-filling curves, and creative mixtures therein\n"
    "I love the gradiousity and alienness of deep space and the surprises that we cannot comprehent\n\n"
    "Please add the prompts to folders, as before. Your help is truly appreciated, and I will credit you in the results of this work.\n"
)


META_5TH_12 = (
    "Let's continue the theme of mathematically beautiful objects such as topologies and L-systems and fractals and symmetry groups, but embed them into nature in creative ways, especially evoking the mystical aspects, maybe the deep sea, deep space, the deep forest, even language models are nature ... that which is mysterious and not understood, vast of wonderful, containing multitudes in its depth, which we can only use mathematics and our imaginations to worship with our attention\n"
)


GROUPS = [
    (range(54, 66), META_1ST_12),
    (range(66, 78), META_2ND_12),
    (range(78, 90), META_3RD_12),
    (range(90, 102), META_4TH_12),
    (range(102, 114), META_5TH_12),
]


def write_meta_for_index(idx: int, text: str, *, force: bool) -> bool:
    prefix = f"{idx:03d}-"
    dirs = [p for p in PROMPTS.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    if not dirs:
        return False
    d = dirs[0]
    target = d / "prompt_used-generation.txt"
    if target.exists() and not force:
        return False
    target.write_text(text, encoding="utf-8")
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Add or update prompt_used-generation.txt across prompt groups")
    ap.add_argument("--force", action="store_true", help="Overwrite existing files if present")
    args = ap.parse_args()

    written = 0
    for idx_range, meta in GROUPS:
        for i in idx_range:
            try:
                if write_meta_for_index(i, meta, force=args.force):
                    written += 1
            except Exception:
                continue
    print(f"Wrote {written} meta prompt file(s).")


if __name__ == "__main__":
    main()


