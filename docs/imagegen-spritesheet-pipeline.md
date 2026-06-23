# Pipeline spritesheet par génération d'images

Ce document décrit le flux **mode image** : actions statiques ou pose boards multi-frames (`idle`, `attack`, `hurt`, `jump`, `death`, etc.).

## Quand utiliser ce pipeline

- Actions **one-shot** ou **boucles courtes** sans besoin de mouvement fluide vidéo
- Profil **platformer** par défaut pour idle/attack/hurt/jump/death
- Alternative plus prévisible que la vidéo pour les poses fixes

## Étapes

```text
Ancre W 1024×1024 (chroma)
    → Génération pose board (4×3 cellules sur fond chroma)
    → Récupération des composants foreground
    → Pixel-snap optionnel
    → Normalisation en cellules 256×256
    → Spritesheet 5 colonnes + GIF preview
    → finalize-runtime
```

## Pose boards

| Preset | Taille | Cellules | Cellule |
|--------|--------|----------|---------|
| `standard` | 1536×1152 | 4×3 | 384×384 |
| `hires` | 2048×1536 | 4×3 | 512×512 |

La zone **runtime sûre** est un carré **256×256** centré dans chaque cellule de génération.

`hires` améliore la qualité source ; l'export moteur reste en 256×256.

## Commande type

```bash
uv run spriterrific run-actions \
  --actions idle,attack,hurt,jump,death \
  --direction w \
  --reference runs/bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/character-actions \
  --mode image \
  --pose-board-preset hires \
  --frame-prompt-style loose \
  --pixel-snap \
  --pixel-snap-source chroma-layout \
  --k-colors 64
```

## Pixel-snap source

| Valeur | Comportement |
|--------|--------------|
| `recovered` | Snap indépendant par frame récupérée |
| `chroma-layout` | Échelle partagée sur canvas chroma (recommandé vidéo stable) |
| `transparent-layout` | Comme chroma-layout mais fond transparent |

## Frames recommandées (platformer)

| Action | Frames |
|--------|--------|
| idle | 10 |
| attack | 8 |
| hurt | 6 |
| jump | 6 |
| death | 10 |
| crouch | 6 |

Utilisez `--strict-frame-counts` pour refuser les valeurs hors liste.

## Pose boards existants (sans regénération)

Si vous avez des images générées ailleurs :

```text
runs/imagegen-root/
  idle-w/generated/sheet.png
  attack-w/generated/sheet.png
  ...
```

```bash
uv run spriterrific run-actions \
  --existing-sheet-root runs/imagegen-root \
  --reference runs/bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  ...
```

## Artefacts de revue

Chaque run doit exposer :
- source / pose board généré
- composants récupérés
- frames natives paddées (contact sheet, GIF)
- comparaison avant/après pixel-snap
- spritesheet et GIF runtime
- `review/index.md` avec commande de suite

## Promotion

Ne copiez pas directement `export/` sans `finalize-runtime` si `publicAssetReady` est absent.

Voir : [Tutoriel](tutoriel.md), [walk-cycle-video-pipeline.md](walk-cycle-video-pipeline.md).
