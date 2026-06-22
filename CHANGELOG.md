# Changelog

Historique des versions du fork **SpriterificMadHacademic** et du paquet Spriterrific sous-jacent.

## [Non publié] — Fork MadHackademie

### Ajouté
- Documentation française complète dans `docs/`
  - Tutoriel pas à pas (`docs/tutoriel.md`)
  - Guide clés API (`docs/cles-api.md`)
  - Installation, CLI, Studio, opérateur, pipelines techniques
- Fichier `.env.example` versionné
- `SETUP-MADHACKADEMIE.md` — notes de progression du fork

### Modifié
- `.gitignore` — exception pour `.env.example`
- `README.md` — liens documentation corrigés, section MadHackademie

---

## [0.11.2] — 2025 (upstream Spriterrific)

Version importée depuis PyPI comme base du fork.

### Fonctionnalités principales
- Pipeline CLI bootstrap ancres + animations image/vidéo
- Templates : platformer, fighting-game, point-and-click
- Presets candidat : lobit-v1, high-fidelity-v1, preserve-reference-v1
- Outils GUI : viewer, frame-picker, frame-aligner, sprite-cleanup, anchor-wizard-gui
- API FastAPI + interface web bootstrap
- Skill agent pour Claude/Cursor/Codex
- finalize-runtime, size-contract, despill
- Support 8 directions, rts-oblique, actions aventure

### Statut
- Alpha — revue humaine requise aux étapes clés
- CLI = chemin production principal
- API/Studio = expérimental

---

## Liens

- Dépôt fork : https://github.com/madhackademie/SpriterificMadHacademic
- Projet upstream : https://spriterrific.com
- Documentation : [docs/README.md](docs/README.md)
