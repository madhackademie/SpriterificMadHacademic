# Référence des commandes CLI

Toutes les commandes s'exécutent via :

```bash
uv run spriterrific <commande> [options]
```

(`spriterrific` directement si installé via pipx.)

---

## Pipeline principal

### `run`

Génère **une** animation (image ou vidéo) à partir d'une ancre de référence.

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --reference runs/.../anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/mon-run \
  --mode video
```

Options importantes :
- `--mode image|video` — force le mode (sinon défaut selon l'action)
- `--frames N` — nombre de frames final
- `--preset-profile platformer|fighting-game|point-and-click`
- `--animation-template` — vocabulaire projet (mappe vers le profil)
- `--video-model grok-imagine-video-i2v|wan-2.7|seedance-2.0-i2v|...`
- `--video-duration` — durée clip (selon modèle)
- `--end-reference` — image finale (transitions `get_up`, etc.)
- `--chroma "#RRGGBB"` — couleur matte
- `--pixel-snap` / `--k-colors`
- `--dry-fal` — sans appel API
- `--seed N` — graine reproductible (modèles supportés)
- `--existing-video` / `--selected-order` / `--selected-range` — recovery manuel

### `run-actions`

Lot d'actions **image** en séquence.

```bash
uv run spriterrific run-actions \
  --actions idle,attack,hurt,jump,death \
  --direction w \
  --reference runs/.../anchor-snapped-1024-chroma.png \
  --run-dir runs/actions-batch \
  --mode image
```

- `--existing-sheet-root` — pose boards déjà générés
- `--pose-board-preset standard|hires`

---

## Ancres (bootstrap)

### `bootstrap-anchors`

Workflow complet texte/image → candidat → ancres directionnelles.

```bash
uv run spriterrific bootstrap-anchors \
  --character-id <id> \
  --source-prompt "..." \
  --source-image path.png \
  --directions w \
  --game-view platformer \
  --anchor-role character \
  --anchor-context "..." \
  --candidate-prompt-preset lobit-v1|high-fidelity-v1|preserve-reference-v1 \
  --pixel-snap-anchor / --no-pixel-snap-anchor \
  --k-colors 64 \
  --run-dir runs/... \
  --config config.json \
  --resume \
  --dry-fal
```

### `anchors`

Ancres directionnelles depuis **une** image de référence existante.

### `anchor-wizard`

Même logique en étapes : `--stage candidate|directions|all`

### `anchor-wizard-gui`

Interface graphique Tkinter pour le workflow ancres.

### `accept-anchor`

Promouvoir une ancre manuellement corrigée :

```bash
uv run spriterrific accept-anchor \
  --run-dir runs/bootstrap \
  --direction w \
  --source chemin/vers/anchor-1024-chroma.png
```

### `preprocess` / `snap`

Pré-traitement et pixel-snap d'une image utilisateur vers ancre 1024×1024.

---

## Post-traitement

### `frame-picker`

GUI — sélection de frames depuis une vidéo extraite.

### `process-selection`

Transforme une sélection frame-picker en spritesheet runtime.

```bash
uv run spriterrific process-selection \
  --picker-dir runs/.../frame-picker/<ts> \
  --out-dir runs/.../post-selection/walk \
  --action walk \
  --direction w \
  --preserve-motion \
  --pixel-snap \
  --size-contract characters/id/size-contract.json
```

### `frame-aligner`

GUI — ajustement pixel par pixel des frames 256×256.

### `sprite-cleanup`

GUI — crayon, gomme, pipette sur sheet ou frames.

### `despill`

Corrige les franges de couleur matte sans relancer le pipeline :

```bash
uv run spriterrific despill --sheet export/spritesheet.png --chroma "#00FF00"
```

### `finalize-runtime`

Marque les assets prêts pour le jeu (`publicAssetReady: true`).

```bash
uv run spriterrific finalize-runtime \
  --input-dir runs/.../post-selection/walk \
  --output-dir runs/.../final/walk \
  --anchor-policy auto|grounded|preserve-motion|centered
```

### `clean-frames` / `sheet-frames`

Étapes bas niveau de nettoyage et assemblage de frames.

---

## Contrats et validation

### `size-contract`

Dérive un JSON de taille depuis un asset approuvé :

```bash
uv run spriterrific size-contract \
  --source public/assets/.../idle.png \
  --out characters/id/size-contract.json \
  --pivot foot-center
```

### `audit-size-contract`

Vérifie la conformité d'un export au contrat.

### `inspect` / `validate`

```bash
uv run spriterrific inspect --run-dir runs/...
uv run spriterrific validate --run-dir runs/...
```

---

## Navigation et utilitaires

### `viewer`

Navigateur de runs avec lancement des outils GUI.

```bash
uv run spriterrific viewer
uv run spriterrific viewer --run-dir runs/mon-run
uv run spriterrific viewer --project-dir /chemin/projet
```

### `skill`

```bash
uv run spriterrific skill install --target all
uv run spriterrific skill install --dest .claude/skills --force
```

---

## Actions disponibles

| Action | Mode défaut | Frames défaut | Type |
|--------|-------------|---------------|------|
| idle | image | 10 | boucle |
| attack | image | 8 | one-shot |
| hurt | image | 6 | one-shot |
| jump | image | 6 | transition |
| death | image | 10 | transition |
| crouch | video | 6 | hold |
| walk | video | 8 | boucle |
| run | video | 8 | boucle |
| talk, interact, pick_up, use, examine, give, shrug | video | 10–12 | aventure |
| walk_forward, walk_backward, block_high, block_low | video | 8–12 | fighting |
| knockdown, get_up, light_attack, heavy_attack | video | 8–12 | fighting |

Directions : `n`, `ne`, `e`, `se`, `s`, `sw`, `w`, `nw`

---

## Vues jeu (`--game-view`)

| Valeur | Usage |
|--------|-------|
| `platformer` | Plateforme 2D côté (défaut) |
| `adventure` | Point-and-click |
| `rts-oblique` | Unités RTS type Warcraft |
| `top-down` | Expérimental |
| `isometric` | Expérimental |

---

## Aide détaillée

```bash
uv run spriterrific run --help
uv run spriterrific bootstrap-anchors --help
```

Voir aussi : [Tutoriel](tutoriel.md), [Guide opérateur](operator-guide.md).
