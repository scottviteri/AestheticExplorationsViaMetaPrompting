# Devotional Geometry

A working space for generating and curating visual prompts that reflect a mathematical–mystical aesthetic (self-reference, geometry, information flow, “wisdom of nature,” Miyazaki-adjacent calm), plus lightweight analysis of prior conversations to mine themes for future prompts.

## Repository layout

- `PersonalDocuments/`
  - Personal notes and reference documents (e.g., `conversations.json`).
- `GPTConversationAnalysis/`
  - `themes/`: outputs from the theme extractor
    - `themes_per_conversation.jsonl`: minimal 3–7 short tags per conversation
    - `themes_rollup.md`: unique tags across the slice
    - `interesting_conversations.jsonl`: model/heuristic-selected subset for image-prompt-worthy ideas
  - `aesthetics.md`: legacy aesthetic notes (generator now uses internal guidance and manual vibe names)
- `prompts/`
  - One subdirectory per prompt (e.g., `114-julia-set-opaline-glass/`)
    - `prompt.txt`: source prompt text
    - `prompt_used-generation.txt`: exact system prompt used to produce `prompt.txt`
    - `prompt_used-<tag>.txt`: exact text sent to the image model for that output
    - `front-<tag>.png`: generated image (non-clobbering variant filenames supported)
    - `front-<tag>-gma42.png`: auto-brightened version
    - `back.tex` + `back.pdf`: printable back-of-card with the prompt text
- `scripts/`
  - `generate_cards.py`: generate per-prompt fronts with OpenAI Images and printable backs; supports batch printing and retro back updates
  - `generate_fresh_prompts.py`: generate new prompt folders using internal guidance and manual aesthetic vibe names (Responses API, structured outputs)
  - `brighten_existing_images.py`: retroactively create brightened `-gma42` images for existing prompts
  - `theme_extractor.py`: parallel, low-cost theme extraction over a conversation slice (incremental writes)
  - `theme_filter.py`: incremental filter that writes interesting conversations to `interesting_conversations.jsonl`
  - `philosophy_filter.py`: filters `interesting_conversations.jsonl` down to philosophically interesting items via `gpt-5-nano` (structured boolean) with heuristic fallback

## Image generation (OpenAI Images)

- Provider: OpenAI `gpt-image-1`
- Conformance: outputs are resized/cropped to 1800×1200 px (3:2) at 300 DPI for 4×6 printing
- Quality: requests use `quality="high"`
- Brightening: each generated image automatically produces a `-gma42.png` via ImageMagick gamma correction
 - Front printing: by default prints the brightened `-gma42` image; can be disabled with a CLI flag

### Generate images from prompt folders

1) Environment

- `OPENAI_API_KEY` (required)
- `PRINTER_NAME` (optional; defaults to `MG3620` for printing examples)

2) Run (examples)

```bash
# List prompt folders
python3 scripts/generate_cards.py list

# Generate for a range (by folder index prefix)
python3 scripts/generate_cards.py generate --start 114 --end 120 --concurrency 2

# Print a specific index (front+back). Use brightened front by default; disable with --no-use-brightened
python3 scripts/generate_cards.py print --index 114 --side both

# Batch print many fronts or backs (submits one job per item)
python3 scripts/generate_cards.py batch-print --side front --start 120 --end 140
python3 scripts/generate_cards.py batch-print --side back  --start 120 --end 140
```

Notes
- Uses `prompts/*/prompt.txt` as source-of-truth; if `back.tex/pdf` are missing, they are created from `prompt.txt`.
- Non-clobbering filenames: new fronts use `front-<tag>-2.png`, `-3.png`, etc., preserving earlier variants.
- Brightened versions are saved alongside as `front-*-gma42.png`.
- Printing options:
  - Fronts (photo): 4×6 media with full bleed, glossy paper, high quality, photo optimization
  - Backs (text on photo paper): 4×6, glossy media, grayscale

Backs include a bottom-right two-line footer:
"Metaprompt by Scott; Prompt by GPT-5; Image by GPT Image 1\nYutong & Scott's Wedding 8/31/2025"

Retroactively update backs to include the footer and recompile PDFs:
```bash
python3 scripts/generate_cards.py update-backs --start 1 --end 10000
```

## Generate fresh prompts (structured Responses API)

The fresh prompt generator uses internal guidance and manual aesthetic vibe names (not `aesthetics.md`) and calls the OpenAI Responses API with structured outputs (JSON Schema). It excludes the historical `prompts.md` library to avoid bias toward past outputs. It now prefers `GPTConversationAnalysis/themes/philosophically_interesting_conversations.jsonl` for diversity cues, falling back to `interesting_conversations.jsonl` if the philosophical file is absent.

```bash
# Batch mode (single call returns N prompts). Uses Responses API with JSON Schema; GPT-5 supported
python3 scripts/generate_fresh_prompts.py --count 8 --model gpt-5

# Concurrent mode (N parallel calls, one prompt per call)
python3 scripts/generate_fresh_prompts.py --count 8 --concurrent --concurrency 4 --model gpt-5

# Dry run (no folders written; shows planned slugs and token usage)
python3 scripts/generate_fresh_prompts.py --count 3 --dry-run
```

Behavior
- Creates new `prompts/{NNN-slug}/` folders at the next available index
- Writes `prompt.txt` and `prompt_used-generation.txt` (the exact system prompt used)
- Prints output token usage after each model call (per-prompt in concurrent mode; per-batch in batch mode)
 - Always uses Responses API; structured outputs enforced with JSON Schema
 - Manual aesthetic vibe names are included in the system prompt

## Brighten existing images

Create `-gma42` brightened versions for all existing fronts:

```bash
python3 scripts/brighten_existing_images.py
```

## Conversation theme extraction (parallel)

Produces only a few short tags per conversation to minimize cost/time. Transcripts are truncated to ~2,000 chars. Writes are incremental and cumulative (no overwrite) and the rollup is regenerated at the end.

Run:

```bash
python3 scripts/theme_extractor.py --start 1 --end 10 --concurrency 3
```

Outputs:
- `GPTConversationAnalysis/themes/themes_per_conversation.jsonl`
- `GPTConversationAnalysis/themes/themes_rollup.md`

### Theme filtering (interesting subset)

```bash
# Heuristic only
python3 scripts/theme_filter.py --start 1 --end 200

# Model-backed decision
python3 scripts/theme_filter.py --start 1 --end 200 --use-model --model gpt-4o-mini
```

### Philosophy filtering (subset of interesting)

```bash
# From interesting to philosophically interesting (model with strict structured outputs; heuristic fallback)
python3 scripts/philosophy_filter.py --start 1 --end 200 --model gpt-5-nano
```

Outputs:
- `GPTConversationAnalysis/themes/philosophically_interesting_conversations.jsonl`

## Current status

- OpenAI Images only (no Replicate/Imagen paths)
- Fronts generated with `quality="high"`, auto-brightened `-gma42` saved; front printing prefers brightened variant
- Non-clobbering output filenames for multiple variants
- Prompt generator uses Responses API (JSON Schema structured outputs), internal guidance + manual vibe names; token usage printed
- Concurrent generation supported for both prompts and images
- Backs include a right-aligned footer with credits and wedding line; `update-backs` available to retrofit existing prompts

## Requirements

- Python deps: see `requirements.txt`
- System tools: ImageMagick (`magick`) and XeLaTeX (`xelatex`)

## Troubleshooting

- Ensure `OPENAI_API_KEY` is set
- If images don’t brighten, ensure ImageMagick is installed and `magick` is on PATH
- For printing, adjust `PRINTER_NAME` and print options in `scripts/generate_cards.py`

## Publishing

This repo can be made public by excluding private/source data while keeping reproducible code and assets:

- Excluded by `.gitignore` (privacy):
  - `PersonalDocuments/`
  - `GPTConversationAnalysis/themes/themes_per_conversation.jsonl`
  - `GPTConversationAnalysis/themes/themes_rollup.md`
  - `GPTConversationAnalysis/themes/interesting_conversations.jsonl`

How to publish:
1) Initialize and commit
   ```bash
   git init
   git add .
   git commit -m "Initial public import: code, prompts, and docs (private data excluded)"
   ```
2) Add remote and push
   ```bash
   git remote add origin <YOUR_REPO_URL>
   git branch -M main
   git push -u origin main
   ```

## License

Internal research/creative project; no explicit license specified.
