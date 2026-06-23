# Setup MadHackademie — Spriterrific fork

Note de progression pour la mise en place du fork local.

**Documentation complète** : voir [`docs/README.md`](docs/README.md) — en particulier le [tutoriel](docs/tutoriel.md) et le [guide des clés API](docs/cles-api.md).

## Historique

| Date | Action | Commit |
|------|--------|--------|
| 2026-06-22 | Import Spriterrific 0.11.2 depuis PyPI | `94fdcfc` |
| 2026-06-22 | Nettoyage fork (`.gitignore`, suppression `test.txt` et tarball) | `7b90edb` |
| 2026-06-22 | Doc setup + `uv.lock` | `a13c197` |
| 2026-06-22 | Documentation FR complète + `.env.example` | en cours |

## Étape 1 — Environnement local

### Fait

- [x] `uv` installé via Python 3.13 (`py -3.13 -m pip install uv`)
- [x] Dépendances installées : `py -3.13 -m uv sync`
  - `.venv` créé avec Python **3.13.0**
  - 31 paquets (spriterrific, fastapi, pillow, numpy, pytest, etc.)
- [x] CLI vérifiée : `py -3.13 -m uv run spriterrific --help`
- [x] `.env.example` créé et versionné (modèle pour les clés API)
- [x] Documentation française dans `docs/` (tutoriel, clés API, CLI, pipelines)

### À finir

- [ ] Terminer `py -3.13 -m uv run pytest` sur chaque poste (215 tests)
- [ ] Créer `.env` à partir de `.env.example` et renseigner `FAL_KEY` sur chaque machine
- [ ] Premier run bootstrap réussi (étape 2)

### Commandes utiles

```powershell
cd c:\SpriterificMadHackAdemic\SpriterificMadHacademic

# Toujours utiliser Python 3.13 (le `python` par défaut est 3.10.8)
py -3.13 -m uv run spriterrific --help
py -3.13 -m uv run pytest

# Config API — voir docs/cles-api.md
copy .env.example .env
# puis éditer .env avec votre clé fal.ai
```

### Point d'attention

Sur la machine de développement initiale :

- `python` → **3.10.8** (insuffisant, Spriterrific exige ≥ 3.11)
- `uv` n'est pas dans le PATH global → utiliser **`py -3.13 -m uv`**

**Chaque ordinateur** doit cloner le repo, lancer `uv sync`, et créer son propre `.env`. Seul le code est sur GitHub.

## Étape 2 — Premier run

Suivre le [tutoriel complet](docs/tutoriel.md). Résumé :

```powershell
py -3.13 -m uv run spriterrific bootstrap-anchors `
  --character-id mon-personnage `
  --source-prompt "héros pixel art, silhouette lisible" `
  --directions w `
  --game-view platformer `
  --run-dir runs/mon-personnage-bootstrap
```

Ou interface graphique :

```powershell
py -3.13 -m uv run spriterrific anchor-wizard-gui
```

## Étape 3 — Personnalisation fork MadHackademie (à venir)

- Adapter README / branding
- Conserver licence Apache-2.0 et fichier `NOTICE`
- Presets pédagogiques pour ateliers / game jams
- Installer le skill agent dans les projets étudiants :

```powershell
cd votre-projet-de-jeu
py -3.13 -m uv run spriterrific skill install --target all
```

## Index documentation

| Document | Description |
|----------|-------------|
| [docs/tutoriel.md](docs/tutoriel.md) | Tutoriel pas à pas |
| [docs/cles-api.md](docs/cles-api.md) | Clés fal.ai, coûts, sécurité |
| [docs/installation.md](docs/installation.md) | Installation par machine |
| [docs/commandes-cli.md](docs/commandes-cli.md) | Référence CLI |
| [docs/operator-guide.md](docs/operator-guide.md) | Revue et production |
