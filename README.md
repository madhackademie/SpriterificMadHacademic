# Spriterrific

Turn a character prompt or reference image into game-ready pixel spritesheets.

Spriterrific is a local Python asset pipeline for AI-assisted 2D game characters. It helps you create a clean character anchor, generate animations, recover frames, curate motion, and export spritesheets, GIF previews, and metadata your game can load.

[Watch the short promo reel](docs/assets/readme/spriterrific-promo-reel-16x9.mp4) | [Read the Studio guide](docs/studio-readme.md) | [Read the operator guide](docs/operator-guide.md) | [See the changelog](CHANGELOG.md)

![Spriterrific promo storyboard](docs/assets/readme/spriterrific-promo-reel-16x9-contact.png)

## What You Can Make

Start with a prompt or image. Choose the animations your game needs. Export clean runtime assets.

| Clean pixel character | Running preview | Runtime spritesheet |
| --- | --- | --- |
| ![Robin Chute pixel character](docs/assets/readme/robin-front-pixel-snapped.png) | ![Robin Chute run animation](docs/assets/readme/robin-run.gif) | ![Robin Chute run spritesheet](docs/assets/readme/robin-run-spritesheet.png) |

More action examples:

| Attack | Death | Run |
| --- | --- | --- |
| ![Attack animation](docs/assets/readme/robin-attack.gif) | ![Death animation](docs/assets/readme/robin-death.gif) | ![Run animation](docs/assets/readme/robin-run.gif) |

## Why Spriterrific Exists

AI models can produce promising game art, but the raw outputs are rarely ready for an engine. Spriterrific adds the missing production steps:

- Generate or import a character reference.
- Distill it into a clean pixel-art anchor when pixel snapping is desired.
- Generate facings and animations from accepted anchors.
- Split video or image generations into recoverable frames.
- Pick frames with timing-aware defaults and align them with local review tools.
- Pixel snap, clean, normalize, pack, and preview spritesheets.
- Write run metadata so work can be debugged, resumed, and audited.

The goal is not one magic prompt. The goal is a repeatable asset pipeline.

## Current Happy Path

1. Provide a text prompt or reference image.
2. Generate a clean front-facing pixel character.
3. Generate a side-facing anchor, usually `w` for platformers.
4. Choose animations such as `idle`, `attack`, `hurt`, `jump`, `death`, `walk`, `run`, or `crouch`.
5. Generate short image or video motion samples.
6. Use the frame picker and frame aligner to curate the result.
7. Export spritesheets, GIF previews, and metadata for your game.

## Animation Templates

Spriterrific keeps the Python engine actions deliberately generic, then lets
the SDK and Studio expose friendlier project vocabularies.

- `platformer` is the default template for side-view game characters. It
  focuses on `idle`, `attack`, `hurt`, `death`, `walk`, `jump`, and `crouch`.
- `fighting-game` is for brawler/fighter workflows. The SDK/Studio can ask for
  actions such as `light-punch`, `heavy-kick`, `block-high`, `knockdown`, and
  `get-up`, while the engine records the underlying generic motion contract
  such as `light_attack`, `heavy_attack`, `block_high`, or `get_up`.
- `point-and-click` is for adventure-game characters. It includes
  `idle`, `walk`, `talk`, `interact`, `pick_up`, `use`, `examine`, `give`, and
  `shrug`, with slightly longer defaults for dialogue and object-interaction
  gestures. These adventure verbs are video-first by default. `adventure` is
  accepted as the same template family.

Use `--animation-template fighting-game` with SDK/Studio workflows when you
want fighting-game action names. Use `--preset-profile fighting-game` with the
raw CLI when you are running the generic engine actions directly.

For point-and-click adventure work, use `--animation-template point-and-click`
or `--preset-profile point-and-click`. The current left-facing adventure
convention is `--direction sw`, which means front-left three-quarter rather
than a true platformer side profile.

Frame counts are recommendations, not universal laws. In normal CLI/SDK runs,
unsupported requested counts are coerced to the nearest recommended count and
recorded in run metadata. Use `--strict-frame-counts` when you want invalid
counts to fail before a provider call.

## Output Styles

Spriterrific supports two practical art targets:

- **Pixel-snap / real pixels**: simpler low-bit art that can be recovered onto a real pixel grid. Best when you want editable, palette-controlled retro sprites.
- **Mixels / high fidelity**: richer AI-generated pixel texture where mixed pixels are acceptable. Best when the game resolution is high enough that strict pixel purity is less important.

If you intend to pixel snap, start from a pixel-snapped anchor. This matters even when the final animation comes from image-to-video.

Use the default `lobit-v1` candidate style when you want Spriterrific to distill a prompt or image into its opinionated snap-ready low-bit style. If you want richer high-fidelity/mixel game art and do not want the anchor pixel-snapped, use:

```bash
--candidate-prompt-preset high-fidelity-v1 \
--no-pixel-snap-anchor
```

If you already have a reference image whose style must be preserved, use:

```bash
--source-image path/to/reference.png \
--candidate-prompt-preset preserve-reference-v1
```

`preserve-reference-v1` treats the source image as strict visual authority for proportions, palette, line weight, rendering style, silhouette, and outfit cues. Pixel snapping remains a separate choice: pair it with `--pixel-snap-anchor` to snap/clean the reference style, or `--no-pixel-snap-anchor` to keep richer mixels.

The high-fidelity and preserve-reference choices also use less low-bit source prompting for prompt-only runs, so the source does not start from strict lobit constraints unless you ask for them.

## Quick Start

Try it without installing:

```bash
uvx spriterrific --help
```

Or install it as a tool:

```bash
pipx install spriterrific
# or
uv tool install spriterrific
# or plain pip
pip install spriterrific
```

The examples in this README use `uv run spriterrific ...` (running from a source checkout). If you installed via pipx/uv/pip, drop the `uv run` prefix and call `spriterrific ...` directly.

Set provider keys in a `.env` file in your working directory (or export them in your shell) when running live generation:

```text
FAL_KEY=...
FAL_API_KEY=...
REMOVE_BG_API_KEY=...
```

### Agent skill

Spriterrific ships with a bundled agent skill so coding agents (Claude Code, Cursor, Codex) can drive the full anchor/animation workflow for you. Install it into your game project:

```bash
cd your-game-project
spriterrific skill install            # writes .claude/skills/spriterrific
spriterrific skill install --target all   # also .codex/skills and .agents/skills
```

Then ask your agent to "use the spriterrific skill" to generate characters and animations.

### From source

If you are working from a source checkout, use `uv`:

```bash
uv sync
uv run spriterrific --help
uv run pytest
```

## Using Studio

If you prefer the local web UI, start with the [Studio guide](docs/studio-readme.md). The short version: anchors define the character/object, camera view, facing, and art style; animations should use an accepted anchor as the reference and describe only the motion.

## Generate A Character Anchor

From a prompt:

```bash
uv run spriterrific bootstrap-anchors \
  --character-id robin-chute \
  --source-prompt "whimsical human-like forest outlaw, full-body neutral pose, readable silhouette, charming but not goofy" \
  --directions w \
  --game-view platformer \
  --anchor-role character \
  --anchor-context "side-scrolling platformer character, true W profile" \
  --k-colors 64 \
  --run-dir runs/robin-chute-bootstrap
```

From a reference image:

```bash
uv run spriterrific bootstrap-anchors \
  --character-id robin-chute \
  --source-image path/to/reference.png \
  --directions w \
  --game-view platformer \
  --anchor-role character \
  --anchor-context "side-scrolling platformer character, true W profile" \
  --k-colors 64 \
  --run-dir runs/robin-chute-bootstrap
```

From a reference image where the source style should not be redesigned:

```bash
uv run spriterrific bootstrap-anchors \
  --character-id chibi-hero \
  --source-image path/to/chibi-reference.png \
  --candidate-prompt-preset preserve-reference-v1 \
  --directions w \
  --game-view platformer \
  --anchor-role character \
  --anchor-context "side-scrolling platformer character, true W profile" \
  --pixel-snap-anchor \
  --k-colors 64 \
  --run-dir runs/chibi-hero-bootstrap
```

Review the outputs before generating animations:

```text
runs/robin-chute-bootstrap/candidate/front/snapped-1024-chroma.png
runs/robin-chute-bootstrap/candidate/front/anchor-1024-chroma.png
runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png
runs/robin-chute-bootstrap/anchors/w/anchor-1024-chroma.png
runs/robin-chute-bootstrap/review/bootstrap/index.md
```

For enemies, turrets, props, or non-platformer camera views, pass explicit `--game-view`, `--anchor-role`, and `--anchor-context`. Do not rely on a generic character prompt when the asset has special anatomy or camera requirements.

For Warcraft-like RTS units, use `rts-oblique` instead of plain `top-down`:

```bash
uv run spriterrific bootstrap-anchors \
  --character-id orc-warrior \
  --source-prompt "orc warrior for a Warcraft-style top-down RTS, pixel art style but not super low fidelity" \
  --directions n,ne,e,se,s,sw,w,nw \
  --game-view rts-oblique \
  --anchor-role enemy \
  --anchor-context "Warcraft-style elevated RTS unit, readable armor, axe, and broad silhouette" \
  --candidate-prompt-preset high-fidelity-v1 \
  --no-pixel-snap-anchor \
  --k-colors 64
```

`rts-oblique` changes source, candidate, and direction prompts toward an
elevated oblique RTS unit camera. It also treats the base candidate as a
compact south-facing unit rather than a straight-on platformer portrait or tall
character-turnaround sprite. A good RTS-oblique candidate should read as a
small unit footprint, usually around 35-45% of the canvas height, with visible
top planes and clear ground contact. Diagonal directions `ne,se,sw,nw` are
supported for eight-direction anchor sets.

`top-down` and `isometric` are available but experimental. Use `top-down` for
loose overhead / three-quarter overhead sprites, and `isometric` for true
tactics / diamond-tile experiments. They are less proven than `platformer` and
`rts-oblique`.

For classic point-and-click adventure characters, use `adventure`:

```bash
uv run spriterrific bootstrap-anchors \
  --character-id hero \
  --source-image hero.png \
  --directions sw \
  --game-view adventure \
  --anchor-role character \
  --candidate-prompt-preset high-fidelity-v1 \
  --no-pixel-snap-anchor
```

In the adventure profile, `sw` is the left-facing front-three-quarter character
view. Runtime code can mirror that facing when the character design permits it.

## Generate Still Actions

```bash
uv run spriterrific run-actions \
  --actions attack,hurt,jump,death \
  --direction w \
  --reference runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/robin-chute-actions \
  --mode image \
  --pose-board-preset hires \
  --frame-prompt-style loose \
  --pixel-snap \
  --pixel-snap-source chroma-layout \
  --k-colors 64
```

## Generate Walk Or Run

For video-derived motion, short clips usually work better than long cinematic clips. `walk` often needs about two seconds to complete the cycle; many other actions work best around one second when the provider supports it.

Video actions now carry timing semantics. Loop actions such as `idle`, `walk`,
and `run` use a compact cycle-window selection. Transition actions such as
`jump`, `death`, `knockdown`, and `get_up` sample the full source/range and
include the final frame so the export does not cut off before the character
lands, falls, or stands up.

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --mode video \
  --reference runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/robin-chute-walk \
  --video-model grok-imagine-video-i2v
```

If the walk reads too much like a run, first try a slower runtime export and a
wider/later loop-selection window:

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --mode video \
  --reference runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/robin-chute-walk-slow \
  --video-model grok-imagine-video-i2v \
  --video-duration 3 \
  --action-context "slow relaxed walk, upright torso, no sprint lean, one foot near-planted" \
  --fps 7 \
  --cycle-start-fraction 0.2 \
  --cycle-span-factor 6
```

For exact control, use `--selected-range START:END_EXCLUSIVE` or
`--selected-order frame-0002.png,...` with `--existing-video`.

For denser fighting-game exports, keep the same pipeline but choose the
profile/actions that describe the motion. Use `get_up` directly instead of
mapping it to `jump`; get-up starts grounded and ends standing/guarded, while
jump is a takeoff-to-land transition.

For transitions with a known final pose, pass an explicit end reference. For
example, `get_up` can start from the final knockdown frame and end at the
standing directional anchor. Spriterrific will use WAN 2.7 when no video model
is specified, because it supports first+last-frame video.

```bash
uv run spriterrific run \
  --action get_up \
  --direction w \
  --mode video \
  --preset-profile fighting-game \
  --reference runs/fighter-knockdown-w/final-frame-1024.png \
  --end-reference runs/fighter-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/fighter-get-up-w
```

```bash
uv run spriterrific run \
  --action heavy_attack \
  --direction w \
  --mode video \
  --animation-template fighting-game \
  --preset-profile fighting-game \
  --frames 12 \
  --reference runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/fighter-heavy-attack-w
```

Then curate frames:

```bash
uv run spriterrific frame-picker \
  --run-dir runs/robin-chute-walk \
  --frames 8 \
  --action walk \
  --direction w \
  --reference runs/robin-chute-bootstrap/anchors/w/anchor-snapped-1024-chroma.png
```

Process the selected frames:

```bash
uv run spriterrific process-selection \
  --picker-dir runs/robin-chute-walk/frame-picker/<picker-run> \
  --out-dir runs/robin-chute-walk/post-selection/walk-pixel-snap \
  --action walk \
  --direction w \
  --columns 5 \
  --fps 10 \
  --preserve-motion \
  --pixel-snap \
  --k-colors 64
```

Finalize before copying assets into your game:

```bash
uv run spriterrific finalize-runtime \
  --input-dir runs/robin-chute-walk/post-selection/walk-pixel-snap \
  --output-dir runs/robin-chute-walk/final
```

For video/I2V runs, treat fresh preview exports as review-only. A game-ready manifest should include:

```json
{
  "publicAssetReady": true
}
```

Video runs default to preserve-canvas recovery so stable image-to-video frames
do not get cropped and recentered per frame. The cleanup path keys the
configured chroma background to transparent black and writes
`export/preserve-canvas.json` for audit. The default matte is chroma green
`#00FF00`, but green characters should use a safer matte such as magenta:

```bash
uv run spriterrific run \
  --action attack \
  --direction w \
  --mode video \
  --reference runs/orc/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/orc-attack-w \
  --chroma "#FF00FF"
```

Use the same `--chroma` value for anchor bootstrap, action generation, and
post-selection processing so prompts, cleanup, metadata, and review pages agree.
Matte fringe cleanup is chroma-aware: it runs for any saturated matte color
(green `#00FF00`, magenta `#FF00FF`, cyan `#00FFFF`), only before runtime
scaling, and records warnings when too many matte-tinted pixels are removed.
A despill pass then neutralizes the matte tint on the remaining anti-aliased
edge pixels (for green, `g = min(g, max(r, b))`) without deleting pixels or
changing geometry, which removes the residual color bleeding that keying and
the fringe peel leave behind. Use `--no-green-fringe-cleanup` if the character
has important foreground detail close to the matte color.

Provider seeds can be passed through for supported models:

```bash
uv run spriterrific run ... --seed 1234
uv run spriterrific bootstrap-anchors ... --seed 1234
```

## Local Tools Included

Spriterrific includes local tools for the non-glamorous parts of asset production:

- `viewer`: browse every run in a project; preview spritesheets, GIFs, video
  frames, and metadata; switch between frame-picker export branches; and
  launch the editing tools on the selected run.
- `frame-picker`: choose the best frames from dense video extraction.
- `frame-aligner`: nudge runtime frames so the character does not pop around.
- `sprite-cleanup`: pencil, eraser, and dropper cleanup for final sheets or frames.
- `despill`: headless removal of residual matte color bleeding from a finished
  spritesheet or runtime frames, without re-running the pipeline.
- `size-contract`: keep later animations consistent with an accepted runtime size.
- `accept-anchor`: promote a reviewed/manual anchor into the canonical run metadata.

## Using Spriterrific Beside A Game

Use Spriterrific like an asset workstation, not as code embedded inside your game:

```text
~/projects/
  my-game/
  spriterrific-public/
```

Generate and review assets inside `spriterrific-public/runs/`, then copy only accepted final exports into your game:

```text
my-game/assets/characters/robin-chute/
  animations/
    run/
      spritesheet.png
      manifest.json
      preview.gif
```

Keep the run folder as your audit/debug workspace.

## Status

Spriterrific is alpha software. It is useful today, but it still expects human review at the important gates: anchor choice, frame selection, alignment, and final promotion.

The first supported posture is local CLI usage. API and web surfaces exist for experimentation, but the CLI and Python tools are the clearest path for real asset work right now.
