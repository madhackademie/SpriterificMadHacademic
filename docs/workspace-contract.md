# Contrat d'espace de travail

Convention de dossiers et métadonnées pour les runs Spriterrific dans un projet de jeu.

## Philosophie

```text
~/projects/
  mon-jeu/                    # code et assets promus
  SpriterificMadHacademic/    # poste de travail assets (ou spriterrific-public/)
```

- **`runs/`** = atelier verbeux (debug, historique, reprises)
- **`mon-jeu/assets/`** = sous-ensemble promu, propre, versionnable

Ne mélangez pas les runs bruts dans le dépôt du jeu sauf export final validé.

## Racines de runs

| Dossier | Usage |
|---------|-------|
| `runs/` | CLI directe (défaut) |
| `spriterrific-sdk/runs/` | Runs SDK bootstrap |
| `spriterrific-sdk/animation-runs/` | Groupes d'animations SDK |
| `runs/api/` | Runs via API web (`SPRITERRIFIC_API_RUN_ROOT`) |

### Marqueur projet

`.spriterrific/config.json` à la racine du projet jeu :

```json
{
  "version": 1,
  "runRoots": ["runs", "spriterrific-sdk/runs", "spriterrific-sdk/animation-runs"]
}
```

Le `viewer` et les outils de découverte préfèrent ce fichier s'il existe.

## Structure d'un run bootstrap

```text
runs/<character>-bootstrap/
  input/source.png
  candidate/front/
    snapped-1024-chroma.png
    anchor-1024-chroma.png
  anchors/w/
    anchor-snapped-1024-chroma.png
  bootstrap.json
  character.json
  events.jsonl
  review/bootstrap/index.md
  logs/
```

## Structure d'un run animation

```text
runs/<character>-walk/
  run.json
  generated/ ou extracted/
  export/                    # preview automatique (revue)
  frame-picker/<ts>/
    selected/
    selection.json
    report.md
  post-selection/<branch>/
    frames-256x256/
    export/spritesheet.png
    export/preview.gif
    export/manifest.json
  review/
```

## Fichiers métadonnées clés

| Fichier | Contenu |
|---------|---------|
| `run.json` | Résumé du run pipeline |
| `bootstrap.json` | État bootstrap ancres |
| `character.json` | Identité personnage / directions |
| `events.jsonl` | Journal d'événements horodaté |
| `export/manifest.json` | Métadonnées spritesheet |
| `finalize-runtime.json` | Rapport finalisation |

## Gate de promotion (`publicAssetReady`)

Un asset est **prêt pour le moteur** quand :

```json
{
  "publicAssetReady": true
}
```

dans `manifest.json`, **et** un rapport `finalize-runtime.json` existe.

Les exports frais de pipeline vidéo ont `publicAssetReady: false` jusqu'à `finalize-runtime`.

## Copie vers le jeu

```text
mon-jeu/assets/characters/<id>/animations/<action>/
  spritesheet.png
  manifest.json
  preview.gif
```

Conserver le run source pour audit et reprise.

## Outils de navigation

```bash
uv run spriterrific viewer --project-dir ~/projects/mon-jeu
```

Découvre tous les runs, permet de comparer les branches `export/` vs `frame-picker/.../post-selection/.../export/`.

## Skill agent

Pour que Cursor/Claude connaisse ces conventions dans un projet jeu :

```bash
cd mon-jeu
uv run spriterrific skill install --target all
```

Voir : [Guide opérateur](operator-guide.md), [Tutoriel](tutoriel.md).
