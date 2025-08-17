#!/usr/bin/env python3
"""
Generate 4"x6" card images from existing prompt folders.

Features
- Iterate prompt folders under prompts/{index-slug}/
- Use prompt.txt as the source of truth for image prompts (no syncing from back.tex)
- Work even if only prompt.txt exists (optionally create back.tex/pdf from it)
- Generate front-{provider_tag}.png (model outputs) without overwriting existing images
- Provide functions to print front and back via lp/lpr using MG3620 examples

Provider
- openai: OpenAI Images API gpt-image-1 (3:2)
"""

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import concurrent.futures as futures


# Constants
REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONAL_DOCS = REPO_ROOT / "PersonalDocuments"
ANALYSIS_DIR = REPO_ROOT / "GPTConversationAnalysis"
PROMPTS_ROOT = REPO_ROOT / "prompts"

# 4x6 inches in pixels at 300 DPI (landscape)
PRINT_WIDTH_PX = 1800  # 6 inches * 300 dpi
PRINT_HEIGHT_PX = 1200  # 4 inches * 300 dpi

OPENAI_TAG = "gptimage1-openai"

# Printer defaults (Canon MG3620 based on provided examples)
PRINTER_NAME = os.getenv("PRINTER_NAME", "MG3620")
DEFAULT_PHOTO_MEDIA_TYPE = os.getenv("PHOTO_MEDIA_TYPE", "PhotoPlusGloss2")

TEXT_PRINT_CMD = [
    "lpr",
    "-P", PRINTER_NAME,
    "-o", "PageSize=w288h432",
    "-o", "StpOrientation=Landscape",
    "-o", "MediaType=GlossyPaperStandard",
    "-o", "ColorModel=Gray",
    "-o", "Resolution=600dpi",
]


@dataclass
class PromptDirItem:
    index: int
    path: Path
    slug: str


def ensure_dirs() -> None:
    PROMPTS_ROOT.mkdir(parents=True, exist_ok=True)


def _sanitize_tag(tag: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", tag)


def list_prompt_dirs() -> list[PromptDirItem]:
    ensure_dirs()
    items: list[PromptDirItem] = []
    for child in sorted(PROMPTS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        m = re.match(r"^(\d{3})-", child.name)
        if not m:
            continue
        idx = int(m.group(1))
        items.append(PromptDirItem(index=idx, path=child, slug=child.name))
    return items


def run(cmd: List[str], check: bool = True, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, cwd=str(cwd) if cwd else None)


def _with_retries(func_name: str, call, *, max_retries: int = 5, base_delay: float = 2.0):
    for attempt in range(1, max_retries + 1):
        try:
            return call()
        except Exception as e:
            if attempt == max_retries:
                raise
            sleep_s = base_delay * (2 ** (attempt - 1))
            print(f"{func_name} error ({type(e).__name__}: {e}); retrying in {sleep_s:.1f}s...", file=sys.stderr)
            time.sleep(sleep_s)


def _conform_to_print_3x2(input_path: Path, output_path: Path) -> None:
    run([
        "magick", str(input_path),
        "-resize", f"{PRINT_WIDTH_PX}x{PRINT_HEIGHT_PX}^",
        "-gravity", "center",
        "-extent", f"{PRINT_WIDTH_PX}x{PRINT_HEIGHT_PX}",
        "-units", "PixelsPerInch",
        "-density", "300",
        str(output_path),
    ])


def _create_brightened_version(input_path: Path, output_path: Path) -> None:
    """Create a gamma-corrected brightened version using ImageMagick."""
    run([
        "magick", str(input_path),
        "-colorspace", "RGB",
        "-evaluate", "pow", "0.42",
        "-colorspace", "sRGB",
        str(output_path),
    ])


# Removed Replicate/Imagen4 support for simplicity; only OpenAI Images is supported


def generate_image_with_openai(prompt_text: str, output_path: Path) -> None:
    try:
        from openai import OpenAI
    except Exception:
        import openai  # fallback older SDK
        OpenAI = None

    if OpenAI is not None:
        client = OpenAI()
        def do_call():
            return client.images.generate(
                model="gpt-image-1",
                prompt=prompt_text,
                size="1024x1024",
                quality="high",
                n=1,
            )
        result = _with_retries("openai(images.generate)", do_call)
        b64 = result.data[0].b64_json
    else:
        # Legacy SDK fallback
        def do_call():
            return openai.images.generate(
                model="gpt-image-1",
                prompt=prompt_text,
                size="1024x1024",
                quality="high",
                n=1,
            )
        result = _with_retries("openai(images.generate)", do_call)
        b64 = result["data"][0]["b64_json"]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "raw.png"
        with open(tmp, "wb") as fh:
            fh.write(base64.b64decode(b64))
        _conform_to_print_3x2(tmp, output_path)
        
        # Create brightened version
        brightened_path = output_path.with_name(f"{output_path.stem}-gma42{output_path.suffix}")
        _create_brightened_version(output_path, brightened_path)


def write_back_tex(prompt_text: str, tex_path: Path) -> None:
    # TeX Gyre Pagella 4x6, wrapped text
    tex = f"""\\documentclass[12pt]{{article}}
\\usepackage[paperwidth=6in,paperheight=4in,margin=0.5in]{{geometry}}
\\usepackage{{fontspec}}
\\setmainfont{{TeX Gyre Pagella}}
\\usepackage{{microtype}}
\\usepackage{{ragged2e}}
\\usepackage{{adjustbox}}
\\usepackage{{varwidth}}
\\pagenumbering{{gobble}}

\\begin{{document}}
\\noindent
\\begin{{adjustbox}}{{max size={{\\textwidth}}{{\\textheight}}}}
\\begin{{varwidth}}{{\\textwidth}}
\\RaggedRight
\\footnotesize
{latex_escape(prompt_text)}
\\end{{varwidth}}
\\end{{adjustbox}}
\\vfill
{{\\raggedleft\\footnotesize
Metaprompt by Scott; Prompt by GPT-5; Image by GPT Image 1 \\\\
Yutong \\& Scott's Wedding 8/31/2025\\par}}
\\end{{document}}
"""
    tex_path.write_text(tex, encoding="utf-8")


def latex_escape(s: str) -> str:
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    out = []
    for ch in s:
        out.append(repl.get(ch, ch))
    return "".join(out)


def latex_unescape(s: str) -> str:
    # Reverse mapping of latex_escape used in back.tex
    replacements = [
        (r"\\textbackslash{}", "\\"),
        (r"\\&", "&"),
        (r"\\%", "%"),
        (r"\\$", "$"),
        (r"\\#", "#"),
        (r"\\_", "_"),
        (r"\\{", "{"),
        (r"\\}", "}"),
        (r"\\textasciitilde{}", "~"),
        (r"\\textasciicircum{}", "^"),
    ]
    out = s
    for a, b in replacements:
        out = out.replace(a, b)
    return out


def extract_prompt_from_back_tex(back_tex_path: Path) -> Optional[str]:
    try:
        content = back_tex_path.read_text(encoding="utf-8")
    except Exception:
        return None
    # Extract content between "\\footnotesize" line and "\\end{varwidth}"
    start_token = "\\footnotesize"
    end_token = "\\end{varwidth}"
    start_idx = content.find(start_token)
    end_idx = content.find(end_token, start_idx + 1 if start_idx >= 0 else 0)
    if start_idx == -1 or end_idx == -1:
        return None
    mid = content[start_idx + len(start_token):end_idx]
    # Strip leading newlines/spaces introduced by template
    mid = mid.lstrip("\n\r\t ")
    mid = mid.rstrip()
    return latex_unescape(mid)


def compile_tex_to_pdf(tex_path: Path, out_pdf: Path) -> None:
    # Compile in-place; then remove aux/log/out
    run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", str(tex_path)], cwd=tex_path.parent)
    # Move generated PDF if needed
    produced_pdf = tex_path.with_suffix(".pdf")
    if produced_pdf != out_pdf:
        produced_pdf.replace(out_pdf)
    # Clean up aux/log
    for ext in (".aux", ".log", ".out"): 
        p = tex_path.with_suffix(ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass


def print_front(image_path: Path) -> None:
    # Backward-compatible wrapper: default to environment-configured media type
    print_front_with_media(image_path, DEFAULT_PHOTO_MEDIA_TYPE)


def build_photo_print_cmd(paper_media_type: str) -> List[str]:
    return [
        "lp",
        "-d", PRINTER_NAME,
        "-o", "media=w288h432J",
        "-o", f"MediaType={paper_media_type}",
        "-o", "print-quality=5",
        "-o", "resolution=600dpi",
        "-o", "StpColorPrecision=Best",
        "-o", "print-content-optimize=photo",
        "-o", "orientation-requested=4",
        "-o", "StpFullBleed=True",
        "-o", "StpiShrinkOutput=Expand",
    ]


def print_front_with_media(image_path: Path, paper_media_type: str) -> None:
    cmd = build_photo_print_cmd(paper_media_type) + [str(image_path)]
    run(cmd)


def print_back(pdf_path: Path) -> None:
    cmd = TEXT_PRINT_CMD + [str(pdf_path)]
    run(cmd)


def _next_unique_output_path(base: Path) -> Tuple[Path, str]:
    """Return a non-clobbering path by appending -2, -3, ... if needed; also return suffix ("", "-2", ...)."""
    if not base.exists():
        return base, ""
    n = 2
    while True:
        candidate = base.with_name(f"{base.stem}-{n}{base.suffix}")
        if not candidate.exists():
            return candidate, f"-{n}"
        n += 1


def generate_for_prompt_dir(item: PromptDirItem, *, allow_additional: bool = False) -> Tuple[Path, Path, Path]:
    ensure_dirs()
    tag = _sanitize_tag(OPENAI_TAG)
    prompt_dir = item.path

    prompt_txt_path = prompt_dir / "prompt.txt"
    back_tex = prompt_dir / "back.tex"
    back_pdf = prompt_dir / "back.pdf"

    # Determine base prompt: prefer prompt.txt; if missing, fallback to parsing back.tex (no syncing)
    if prompt_txt_path.exists():
        base_prompt = prompt_txt_path.read_text(encoding="utf-8").strip()
    else:
        back_text = extract_prompt_from_back_tex(back_tex) if back_tex.exists() else None
        base_prompt = back_text or ""
        if not base_prompt:
            raise FileNotFoundError(f"Missing prompt.txt (and no usable back.tex) in {prompt_dir}")

    front_png_base = prompt_dir / f"front-{tag}.png"

    should_generate = allow_additional or (not front_png_base.exists())
    front_png = front_png_base
    prompt_used_suffix = ""
    if should_generate:
        # Choose unique filename if base exists
        front_png, prompt_used_suffix = _next_unique_output_path(front_png_base)

        # Construct prompt
        used_prompt = f"{base_prompt}, landscape composition, 3:2 aspect ratio, 4x6 inch print"
        generate_image_with_openai(used_prompt, front_png)
        (prompt_dir / f"prompt_used-{tag}{prompt_used_suffix}.txt").write_text(used_prompt, encoding="utf-8")
        
        # Also create brightened version of the prompt_used file for reference
        if prompt_used_suffix:
            brightened_prompt_path = prompt_dir / f"prompt_used-{tag}{prompt_used_suffix}-gma42.txt"
            brightened_prompt_path.write_text(used_prompt + " (brightened via gamma 0.42)", encoding="utf-8")

    # Ensure back assets exist if missing and we have a base prompt
    if not back_tex.exists():
        write_back_tex(base_prompt, back_tex)
    if not back_pdf.exists() and back_tex.exists():
        compile_tex_to_pdf(back_tex, back_pdf)

    return front_png, back_pdf, back_tex


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate and print per-prompt assets from existing prompt folders")
    sub = p.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate fronts (and ensure backs) for prompt folders")
    gen.add_argument("--limit", type=float, default=0.0, help="Seconds to sleep between API submissions (throttle)")
    gen.add_argument("--concurrency", type=int, default=1, help="Max concurrent image generations")
    gen.add_argument("--max-count", type=int, default=0, help="Maximum number of prompts to process (0 = all)")
    gen.add_argument("--start", type=int, default=1, help="Start index (1-based)")
    gen.add_argument("--end", type=int, default=0, help="End index (inclusive; 0 = till end)")

    pr = sub.add_parser("print", help="Print a generated card front/back/both by index (from folder name prefix)")
    pr.add_argument("--index", type=int, required=True, help="Prompt index (as parsed)")
    pr.add_argument("--side", choices=["front", "back", "both"], default="both")
    pr.add_argument("--use-brightened", dest="use_brightened", action="store_true", default=True, help="Prefer -gma42 brightened image for front prints (default: true)")
    pr.add_argument("--no-use-brightened", dest="use_brightened", action="store_false", help="Do not use brightened image for front prints")
    pr.add_argument("--paper-type", choices=["PhotoPlusGloss2", "GlossyPaperStandard"], default="PhotoPlusGloss2", help="Paper media type for front prints (default: PhotoPlusGloss2)")

    ls = sub.add_parser("list", help="List prompt folders with indices")

    upd = sub.add_parser("update-backs", help="Regenerate back.tex and back.pdf for all prompt folders")
    upd.add_argument("--start", type=int, default=1, help="Start index (1-based)")
    upd.add_argument("--end", type=int, default=0, help="End index (inclusive; 0 = till end)")

    bp = sub.add_parser("batch-print", help="Print many fronts or backs by index range")
    bp.add_argument("--side", choices=["front", "back"], required=True)
    bp.add_argument("--start", type=int, default=1, help="Start index (1-based)")
    bp.add_argument("--end", type=int, default=0, help="End index (inclusive; 0 = till end)")
    bp.add_argument("--limit", type=float, default=0.0, help="Seconds to sleep between print submissions")
    bp.add_argument("--use-brightened", dest="use_brightened", action="store_true", default=True, help="Prefer -gma42 brightened image for front prints (default: true)")
    bp.add_argument("--no-use-brightened", dest="use_brightened", action="store_false", help="Do not use brightened image for front prints")
    bp.add_argument("--paper-type", choices=["PhotoPlusGloss2", "GlossyPaperStandard"], default="PhotoPlusGloss2", help="Paper media type for front prints (default: PhotoPlusGloss2)")

    return p


def cmd_generate(args: argparse.Namespace) -> None:
    items = list_prompt_dirs()
    if args.end and args.end < args.start:
        raise SystemExit("--end must be >= --start")

    selected = [p for p in items if p.index >= args.start and (args.end == 0 or p.index <= args.end)]
    if args.max_count:
        selected = selected[: args.max_count]

    print(f"Generating {len(selected)} prompt folders → {PROMPTS_ROOT}")

    # If exactly one target is selected, allow writing an additional variant even if a front exists
    single_target = False
    try:
        # We compute selected before, so reuse below
        pass
    except Exception:
        pass

    def task_fn(item: PromptDirItem) -> Tuple[int, Path, Path]:
        front_png, back_pdf, back_tex = generate_for_prompt_dir(item, allow_additional=(len(selected) == 1))
        return (item.index, front_png, back_pdf)

    # Work queue maintaining up to --concurrency in-flight tasks
    iterator = iter(selected)
    inflight: dict[futures.Future, PromptDirItem] = {}
    submitted = 0
    completed = 0

    with futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        # Pre-fill
        while len(inflight) < max(1, args.concurrency):
            try:
                pmt = next(iterator)
            except StopIteration:
                break
            fut = pool.submit(task_fn, pmt)
            inflight[fut] = pmt
            submitted += 1
            if args.limit:
                time.sleep(float(args.limit))

        # Process as tasks complete, keep invariant on in-flight count
        while inflight:
            for fut in futures.as_completed(list(inflight.keys()), timeout=None):
                pmt = inflight.pop(fut)
                try:
                    _, front_png, back_pdf = fut.result()
                    print(f"#{pmt.index:03d} {pmt.slug} → {front_png} , {back_pdf.name if back_pdf.exists() else 'back.pdf?'}")
                except Exception as e:
                    print(f"Error on index {pmt.index}: {type(e).__name__}: {e}", file=sys.stderr)
                completed += 1

                # Submit next to keep in-flight at target, if work remains
                try:
                    pnext = next(iterator)
                    nfut = pool.submit(task_fn, pnext)
                    inflight[nfut] = pnext
                    submitted += 1
                    if args.limit:
                        time.sleep(float(args.limit))
                except StopIteration:
                    # No more tasks to submit; continue draining
                    pass
                # Break to re-enter as_completed with updated inflight set
                break


def cmd_print(args: argparse.Namespace) -> None:
    items = list_prompt_dirs()
    pmap = {p.index: p for p in items}
    pmt = pmap.get(args.index)
    if pmt is None:
        raise SystemExit(f"Prompt index {args.index} not found")

    front_png, back_pdf, _ = generate_for_prompt_dir(pmt)

    # Optionally substitute brightened version for front
    if args.side in ("front", "both") and args.use_brightened:
        bright = front_png.with_name(f"{front_png.stem}-gma42{front_png.suffix}")
        if bright.exists():
            front_png = bright

    if args.side in ("front", "both"):
        print(f"Printing FRONT: {front_png} (MediaType={args.paper_type})")
        print_front_with_media(front_png, args.paper_type)
    if args.side in ("back", "both"):
        print(f"Printing BACK:  {back_pdf}")
        print_back(back_pdf)


def cmd_list(_: argparse.Namespace) -> None:
    items = list_prompt_dirs()
    for p in items:
        print(f"{p.index:03d}  {p.slug}")

def cmd_batch_print(args: argparse.Namespace) -> None:
    items = list_prompt_dirs()
    selected = [p for p in items if p.index >= args.start and (args.end == 0 or p.index <= args.end)]
    print(f"Batch printing {len(selected)} items: side={args.side}")

    for item in selected:
        # Prefer hyphenated tag but accept underscore variant for backward compatibility
        hyphen_tag = _sanitize_tag(OPENAI_TAG)
        front_png = item.path / f"front-{hyphen_tag}.png"
        if not front_png.exists():
            underscore_tag = _sanitize_tag(OPENAI_TAG.replace("-", "_"))
            alt = item.path / f"front-{underscore_tag}.png"
            if alt.exists():
                front_png = alt
        back_pdf = item.path / "back.pdf"
        try:
            if args.side == "front":
                if args.use_brightened:
                    bright = front_png.with_name(f"{front_png.stem}-gma42{front_png.suffix}")
                    if bright.exists():
                        front_png = bright
                if not front_png.exists():
                    print(f"Skipping {item.slug}: front not found ({front_png.name})", file=sys.stderr)
                else:
                    print(f"Printing FRONT for #{item.index:03d}: {front_png} (MediaType={args.paper_type})")
                    print_front_with_media(front_png, args.paper_type)
            else:
                if not back_pdf.exists():
                    print(f"Skipping {item.slug}: back.pdf not found", file=sys.stderr)
                else:
                    print(f"Printing BACK for #{item.index:03d}: {back_pdf}")
                    print_back(back_pdf)
            if args.limit:
                time.sleep(float(args.limit))
        except Exception as e:
            print(f"Print error for {item.slug}: {e}", file=sys.stderr)


def cmd_update_backs(args: argparse.Namespace) -> None:
    items = list_prompt_dirs()
    selected = [p for p in items if p.index >= args.start and (args.end == 0 or p.index <= args.end)]
    print(f"Updating backs for {len(selected)} prompt folders → {PROMPTS_ROOT}")

    for item in selected:
        prompt_txt_path = item.path / "prompt.txt"
        back_tex = item.path / "back.tex"
        back_pdf = item.path / "back.pdf"

        # Determine base prompt text
        if prompt_txt_path.exists():
            base_prompt = prompt_txt_path.read_text(encoding="utf-8").strip()
        else:
            base_prompt = extract_prompt_from_back_tex(back_tex) or ""
        if not base_prompt:
            print(f"Skipping {item.slug}: no prompt text found", file=sys.stderr)
            continue

        # Rewrite back.tex with footer and recompile PDF
        write_back_tex(base_prompt, back_tex)
        try:
            compile_tex_to_pdf(back_tex, back_pdf)
        except Exception as e:
            print(f"XeLaTeX error for {item.slug}: {e}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.cmd == "generate":
        cmd_generate(args)
    elif args.cmd == "print":
        cmd_print(args)
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "update-backs":
        cmd_update_backs(args)
    elif args.cmd == "batch-print":
        cmd_batch_print(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()


