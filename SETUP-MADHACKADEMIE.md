# Setup MadHackademie — Spriterrific fork

Note de progression pour la mise en place du fork local.

**Documentation complète** : voir [`docs/README.md`](docs/README.md) — en particulier le [tutoriel](docs/tutoriel.md), [lancer le logiciel](docs/lancement.md) et le [guide des clés API](docs/cles-api.md).

## Historique

| Date | Action | Commit |
|------|--------|--------|
| 2026-06-22 | Import Spriterrific 0.11.2 depuis PyPI | `94fdcfc` |
| 2026-06-22 | Nettoyage fork (`.gitignore`, suppression `test.txt` et tarball) | `7b90edb` |
| 2026-06-22 | Doc setup + `uv.lock` | `a13c197` |
| 2026-06-22 | Documentation FR complète + `.env.example` | en cours |
| 2026-06-24 | Doc lancement : Studio web (serveur) vs GUI bureau ; commandes Windows `py -m uv run` | en cours |

## Étape 1 — Environnement local

### Fait

- [x] `uv` installé via Python (`py -m pip install uv`)
- [x] Dépendances installées : `py -m uv sync`
  - `.venv` avec Python **≥ 3.11** (postes atelier : 3.13 ou 3.14)
  - spriterrific, fastapi, pillow, numpy, pytest, etc.
- [x] CLI vérifiée : `py -m uv run spriterrific --help`
- [x] `.env.example` créé et versionné (modèle pour les clés API)
- [x] Documentation française dans `docs/` (tutoriel, clés API, CLI, pipelines)
- [x] Tests : **211 passed**, 4 skipped (ffmpeg absent), sur postes configurés

### À finir

- [ ] Créer `.env` à partir de `.env.example` et renseigner `FAL_KEY` sur chaque machine (si pas déjà fait)
- [ ] Premier run bootstrap réussi (étape 2)
- [ ] (Optionnel) Installer **ffmpeg** pour les 4 tests vidéo skipped

### Commandes utiles (Windows PowerShell)

```powershell
cd m:\SpriterrificMadHack\SpriterificMadHacademic

# Préfixe standard (Python ≥ 3.11 via le lanceur py)
py -m uv run spriterrific --help
py -m uv run pytest

# Config API — voir docs/cles-api.md
copy .env.example .env
# puis éditer .env avec votre clé fal.ai
```

### Lancer le logiciel — trois modes

| Mode | Où ça s'affiche | Commande Windows |
|------|-----------------|------------------|
| **Studio web** | Navigateur | `py -m uv run uvicorn spriterrific.api:app --reload --port 8000` puis ouvrir http://localhost:8000 |
| **GUI bureau** | Fenêtre Tkinter | `py -m uv run spriterrific anchor-wizard-gui` ou `viewer` |
| **CLI** | Terminal | `py -m uv run spriterrific bootstrap-anchors ...` |

> **Studio web** : la console affiche des logs `INFO:` — **pas de fenêtre application**. Ouvrir le navigateur manuellement. Voir [docs/studio-readme.md](docs/studio-readme.md).

### Points d'attention Windows

- `python` peut être une vieille version (ex. 3.10) → toujours **`py -m uv run`**
- `uv` n'est pas toujours dans le PATH → **`py -m uv run`** (uv installé comme module pip)
- **GUI Tkinter** : cocher **tcl/tk and IDLE** à l'installation Python ; ne pas laisser `TCL_LIBRARY` / `TK_LIBRARY` pointer vers une autre version (erreur `init.tcl`)
- **Chaque ordinateur** doit cloner le repo, lancer `uv sync`, et créer son propre `.env`

## Étape 2 — Premier run

Suivre le [tutoriel complet](docs/tutoriel.md). Résumé :

```powershell
py -m uv run spriterrific bootstrap-anchors `
  --character-id mon-personnage `
  --source-prompt "héros pixel art, silhouette lisible" `
  --directions w `
  --game-view platformer `
  --run-dir runs/mon-personnage-bootstrap
```

Ou **Studio web** (navigateur) :

```powershell
py -m uv run uvicorn spriterrific.api:app --reload --port 8000
# → http://localhost:8000
```

Ou **GUI bureau** :

```powershell
py -m uv run spriterrific anchor-wizard-gui
```

## Étape 3 — Personnalisation fork MadHackademie (à venir)

- Adapter README / branding
- Conserver licence Apache-2.0 et fichier `NOTICE`
- Presets pédagogiques pour ateliers / game jams
- Installer le skill agent dans les projets étudiants :

```powershell
cd votre-projet-de-jeu
py -m uv run spriterrific skill install --target all
```

## Index documentation

| Document | Description |
|----------|-------------|
| [docs/lancement.md](docs/lancement.md) | Démarrer Studio web, GUI et CLI |
| [docs/studio-readme.md](docs/studio-readme.md) | Studio web (serveur + navigateur) |
| [docs/tutoriel.md](docs/tutoriel.md) | Tutoriel pas à pas |
| [docs/cles-api.md](docs/cles-api.md) | Clés fal.ai, coûts, sécurité |
| [docs/installation.md](docs/installation.md) | Installation par machine |
| [docs/commandes-cli.md](docs/commandes-cli.md) | Référence CLI |
| [docs/operator-guide.md](docs/operator-guide.md) | Revue et production |
