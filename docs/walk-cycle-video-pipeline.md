# Pipeline marche et animations vidéo

Flux **mode video** pour `walk`, `run`, `crouch` et la plupart des actions fighting-game / point-and-click.

## Principe

1. Partir d'une **plaque** 1024×1024 (ancre chroma)
2. Générer un **clip court** image-to-video via fal.ai
3. **Extraire** toutes les frames denses
4. **Curater** avec frame-picker
5. **Traiter** avec `process-selection` (preserve-canvas par défaut)
6. Optionnel : frame-aligner, finalize-runtime

La vidéo est une **référence de mouvement**, pas l'export final direct.

## Modèle vidéo par défaut

**Grok Imagine** (`grok-imagine-video-i2v`) :
- Clip court (~1 s, ~2 s pour `walk`)
- 720p, ratio 1:1
- Bon compromis identité / coût

Alternatives (comparaison explicite uniquement) :
- `wan-2.2-a14b-i2v-turbo` — très court, pas de durée configurable
- `wan-2.7` — supporte `--end-reference` (get_up, transitions)
- `seedance-2.0-i2v` — plus long (min 4 s), supporte image de fin

## Commande walk

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --mode video \
  --reference runs/bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/character-walk \
  --video-model grok-imagine-video-i2v
```

## Si la marche ressemble à une course

Combiner trois leviers :

```bash
--action-context "marche lente, torse droit, un pied près du sol"
--fps 7
--cycle-start-fraction 0.2
--cycle-span-factor 6
```

Ou sélection manuelle :

```bash
--existing-video chemin/video.mp4 \
--selected-range 12:48 \
--selected-order frame-0012.png,frame-0018.png,...
```

## Sémantique temporelle des actions

| Type | Actions | Sélection |
|------|---------|-----------|
| `loop` | idle, walk, run | Fenêtre de cycle compacte |
| `one_shot` | attack, hurt, light_attack | Fenêtre d'action |
| `transition` | jump, death, knockdown, get_up | Toute la durée + frame finale |
| `hold` | crouch, block_high, block_low | Pose stable |

## Preserve-canvas (défaut vidéo)

Les modèles I2V renvoient des frames de **même taille** sur un canvas fixe. Spriterrific ne recadre pas frame par frame sauf demande explicite (`--layout-mode fit-foreground`).

Le chemin preserve-canvas :
- retire le fond chroma → transparent
- nettoie les franges matte
- conserve le placement source
- écrit `export/preserve-canvas.json` pour audit

L'export automatique est une **preview de revue**, pas l'asset final promu.

## Frame picker → process-selection

```bash
uv run spriterrific frame-picker \
  --run-dir runs/character-walk \
  --frames 8 \
  --action walk \
  --direction w \
  --reference runs/bootstrap/anchors/w/anchor-snapped-1024-chroma.png

uv run spriterrific process-selection \
  --picker-dir runs/character-walk/frame-picker/<ts> \
  --out-dir runs/character-walk/post-selection/walk \
  --action walk \
  --direction w \
  --preserve-motion \
  --pixel-snap-mode locked-grid \
  --columns 5 \
  --fps 10 \
  --k-colors 64
```

`locked-grid` : une seule grille native pour toutes les frames (recommandé vidéo).

## Transitions avec pose finale (`get_up`)

```bash
uv run spriterrific run \
  --action get_up \
  --direction w \
  --mode video \
  --reference runs/knockdown/final-frame-1024.png \
  --end-reference runs/bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/get-up
```

Sans `--video-model`, Spriterrific choisit `wan-2.7` (first+last frame).

## Ombres et sol

Les prompts interdisent ombres portées, lignes de sol, ellipses de contact. Ces éléments appartiennent au **moteur de jeu**, pas au spritesheet.

## Contrat de taille

Si une animation idle est déjà validée :

```bash
uv run spriterrific size-contract \
  --source runs/.../idle/spritesheet.png \
  --out characters/id/size-contract.json

# Puis sur les runs vidéo :
--size-contract characters/id/size-contract.json
```

Voir [size-contracts.md](size-contracts.md).

## Promotion

```text
frame-picker → process-selection → [frame-aligner] → finalize-runtime → copie jeu
```

`manifest.json` doit avoir `publicAssetReady: true`.

Voir : [Tutoriel](tutoriel.md), [Guide opérateur](operator-guide.md).
