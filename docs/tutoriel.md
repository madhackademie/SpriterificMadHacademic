# Tutoriel — De zéro à un personnage jouable

Ce tutoriel vous guide pas à pas pour créer un personnage de jeu 2D avec Spriterrific : ancre, animations, curation, export.

**Durée indicative** : 1 à 3 h selon votre familiarité avec la CLI et le nombre d'animations.

**Prérequis** : [Installation](installation.md) terminée et [clé FAL](cles-api.md) configurée.

---

## Vue d'ensemble

Spriterrific n'est pas un bouton magique « générer spritesheet ». C'est une **chaîne d'étapes** avec des points de revue humaine :

```text
Prompt ou image
    → Ancre (référence du personnage, vue + style)
    → Animations (images ou vidéos courtes)
    → Sélection / alignement des frames
    → Pixel-snap et normalisation
    → Export spritesheet + GIF + manifest.json
    → Copie dans votre jeu
```

Chaque étape produit un dossier `runs/<nom>/` traçable et réversible.

---

## Étape 0 — Choisir votre style

Avant de générer, décidez :

| Mode | Quand l'utiliser | Flags typiques |
|------|------------------|----------------|
| **Pixel-snap** (pixels réels, rétro) | Jeu pixel art, palette contrôlée | défaut `lobit-v1`, `--pixel-snap`, `--k-colors 64` |
| **High-fidelity / mixels** | Jeu HD, texture IA acceptable | `--candidate-prompt-preset high-fidelity-v1 --no-pixel-snap-anchor` |
| **Préserver une image source** | Vous avez déjà un design (chibi, etc.) | `--source-image ... --candidate-prompt-preset preserve-reference-v1` |

**Règle importante** : si le personnage est **vert**, changez la couleur de fond matte :

```bash
--chroma "#FF00FF"
```

Utilisez la **même** valeur pour toutes les commandes (bootstrap, run, process-selection).

---

## Étape 1 — Créer l'ancre du personnage

L'**ancre** est la référence visuelle du personnage (silhouette, costume, palette) pour une direction donnée (souvent `w` = profil gauche en plateforme).

### Option A — Depuis un prompt texte

```bash
uv run spriterrific bootstrap-anchors \
  --character-id mon-heros \
  --source-prompt "héros pixel art forestier, pose neutre, silhouette lisible, corps entier" \
  --directions w \
  --game-view platformer \
  --anchor-role character \
  --anchor-context "personnage plateforme 2D, vrai profil W" \
  --k-colors 64 \
  --run-dir runs/mon-heros-bootstrap
```

### Option B — Depuis une image de référence

```bash
uv run spriterrific bootstrap-anchors \
  --character-id mon-heros \
  --source-image chemin/vers/reference.png \
  --directions w \
  --game-view platformer \
  --run-dir runs/mon-heros-bootstrap
```

### Option C — Interface graphique

```bash
uv run spriterrific anchor-wizard-gui
```

### Fichiers à vérifier

Ouvrez et validez visuellement :

```text
runs/mon-heros-bootstrap/candidate/front/snapped-1024-chroma.png   # candidat face
runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png  # ancre profil W
runs/mon-heros-bootstrap/review/bootstrap/index.md                 # page de revue
```

**Ne passez à l'étape suivante que si l'ancre vous convient.** C'est le verrou qualité le plus important.

### Navigateur de runs

```bash
uv run spriterrific viewer --run-dir runs/mon-heros-bootstrap
```

---

## Étape 2 — Générer les animations statiques (image)

Actions idéales en mode image : `idle`, `attack`, `hurt`, `jump`, `death`.

```bash
uv run spriterrific run-actions \
  --actions idle,attack,hurt,jump,death \
  --direction w \
  --reference runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/mon-heros-actions \
  --mode image \
  --pose-board-preset hires \
  --pixel-snap \
  --pixel-snap-source chroma-layout \
  --k-colors 64
```

Chaque action crée un sous-dossier avec spritesheet, GIF preview et `review/`.

Consultez `runs/mon-heros-actions/review/index.md` pour la synthèse.

---

## Étape 3 — Générer la marche (vidéo)

La marche et la course passent par **image-to-video** (clip court, puis extraction de frames).

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --mode video \
  --reference runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/mon-heros-walk \
  --video-model grok-imagine-video-i2v
```

Modèle par défaut : **Grok Imagine** (~1–2 s de clip). Si la marche ressemble à une course :

```bash
uv run spriterrific run \
  --action walk \
  --direction w \
  --mode video \
  --reference runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/mon-heros-walk-slow \
  --video-duration 3 \
  --action-context "marche lente détendue, torse droit, pas de sprint" \
  --fps 7
```

---

## Étape 4 — Choisir les meilleures frames (frame picker)

```bash
uv run spriterrific frame-picker \
  --run-dir runs/mon-heros-walk \
  --frames 8 \
  --action walk \
  --direction w \
  --reference runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png
```

**Dans l'interface** :
1. Définir frame de début et de fin du cycle
2. Cliquer « Distribute » pour répartir les frames intermédiaires
3. Ajuster frame par frame (clic = sélection, Espace = bascule)
4. Sauvegarder quand la boucle est fluide

Le picker écrit un dossier `frame-picker/<timestamp>/` avec `selection.json` et `report.md`.

---

## Étape 5 — Traiter la sélection

```bash
uv run spriterrific process-selection \
  --picker-dir runs/mon-heros-walk/frame-picker/<timestamp> \
  --out-dir runs/mon-heros-walk/post-selection/walk \
  --action walk \
  --direction w \
  --columns 5 \
  --fps 10 \
  --preserve-motion \
  --pixel-snap \
  --k-colors 64
```

Remplacez `<timestamp>` par le dossier créé par le frame-picker.

---

## Étape 6 — Alignement fin (optionnel)

Si le personnage « saute » d'une frame à l'autre :

```bash
uv run spriterrific frame-aligner \
  --input-dir runs/mon-heros-walk/post-selection/walk/frames-256x256 \
  --out-dir runs/mon-heros-walk/frame-aligner/walk \
  --columns 5 \
  --fps 10 \
  --zoom 3
```

Déplacez chaque frame au pixel près, puis exportez.

---

## Étape 7 — Finaliser pour le moteur de jeu

Avant de copier dans le jeu, appliquez la politique d'ancrage runtime (pieds au même niveau, etc.) :

```bash
uv run spriterrific finalize-runtime \
  --input-dir runs/mon-heros-walk/post-selection/walk \
  --output-dir runs/mon-heros-walk/final/walk
```

Le `manifest.json` doit contenir `"publicAssetReady": true` et un rapport `finalize-runtime.json`.

Répétez pour chaque animation (`idle`, `attack`, etc.) dans leurs dossiers `post-selection` respectifs.

---

## Étape 8 — Copier dans votre jeu

Structure recommandée :

```text
mon-jeu/assets/characters/mon-heros/
  animations/
    idle/
      spritesheet.png
      manifest.json
      preview.gif
    walk/
      spritesheet.png
      manifest.json
      preview.gif
    attack/
      ...
```

Gardez `runs/` comme **archive de debug** — ne supprimez pas avant d'avoir validé les exports.

---

## Récapitulatif des commandes

| Étape | Commande |
|-------|----------|
| Ancre | `bootstrap-anchors` ou `anchor-wizard-gui` |
| Actions image | `run-actions` |
| Action vidéo | `run` |
| Sélection frames | `frame-picker` |
| Traitement | `process-selection` |
| Alignement | `frame-aligner` (optionnel) |
| Nettoyage manuel | `sprite-cleanup` (optionnel) |
| Finalisation | `finalize-runtime` |
| Navigation | `viewer` |

---

## Templates d'animation

| Template | Usage | Commande |
|----------|-------|----------|
| `platformer` | Jeu de plateforme (défaut) | `--animation-template platformer` |
| `fighting-game` | Beat'em up | `--preset-profile fighting-game` |
| `point-and-click` | Aventure point-and-click | `--animation-template point-and-click` |

Exemple combat :

```bash
uv run spriterrific run \
  --action heavy_attack \
  --direction w \
  --mode video \
  --animation-template fighting-game \
  --preset-profile fighting-game \
  --frames 12 \
  --reference runs/mon-heros-bootstrap/anchors/w/anchor-snapped-1024-chroma.png \
  --run-dir runs/mon-heros-heavy-attack
```

---

## Mode sans génération IA (dry-run)

Pour tester la structure sans consommer de crédits :

```bash
uv run spriterrific bootstrap-anchors ... --dry-fal
```

---

## Dépannage rapide

| Symptôme | Piste |
|----------|-------|
| Erreur clé API | Vérifier `.env` et [cles-api.md](cles-api.md) |
| Personnage déformé entre frames | Frame-picker + `process-selection --preserve-motion` |
| Palette qui dérive | Repartir d'une meilleure ancre ; `--k-colors` plus bas |
| Fond vert qui déborde | `--chroma "#FF00FF"` + `despill` si besoin |
| Tests qui échouent sur `uv` | Installer uv ou utiliser `py -3.13 -m uv` |

---

## Aller plus loin

- [Référence CLI complète](commandes-cli.md)
- [Pipeline image détaillé](imagegen-spritesheet-pipeline.md)
- [Pipeline vidéo / marche](walk-cycle-video-pipeline.md)
- [Guide opérateur](operator-guide.md)
