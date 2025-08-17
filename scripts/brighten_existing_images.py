#!/usr/bin/env python3
"""
Retroactively create brightened versions of all existing front-*.png images.

For each front-*.png found in prompt folders, creates a corresponding front-*-gma42.png
using the ImageMagick gamma correction command.
"""

import subprocess
import sys
from pathlib import Path
from typing import List


REPO_ROOT = Path(__file__).resolve().parents[1]
PROMPTS_ROOT = REPO_ROOT / "prompts"


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check)


def create_brightened_version(input_path: Path, output_path: Path) -> None:
    """Create a gamma-corrected brightened version using ImageMagick."""
    run([
        "magick", str(input_path),
        "-colorspace", "RGB",
        "-evaluate", "pow", "0.42",
        "-colorspace", "sRGB",
        str(output_path),
    ])


def main() -> None:
    processed = 0
    skipped = 0
    
    for prompt_dir in PROMPTS_ROOT.iterdir():
        if not prompt_dir.is_dir():
            continue
            
        # Find all front-*.png files (but not already brightened ones)
        for png_file in prompt_dir.glob("front-*.png"):
            if "-gma42" in png_file.name:
                continue  # Skip already brightened images
                
            # Create brightened version path
            brightened_path = png_file.with_name(f"{png_file.stem}-gma42{png_file.suffix}")
            
            if brightened_path.exists():
                print(f"Skipping {png_file.name} (brightened version already exists)")
                skipped += 1
                continue
                
            try:
                print(f"Processing {png_file.name} → {brightened_path.name}")
                create_brightened_version(png_file, brightened_path)
                processed += 1
            except subprocess.CalledProcessError as e:
                print(f"Error processing {png_file.name}: {e}", file=sys.stderr)
                continue
    
    print(f"\nSummary: {processed} images brightened, {skipped} skipped (already existed)")


if __name__ == "__main__":
    main()
