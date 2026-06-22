# Setup MadHackademie — Spriterrific fork

Note de progression pour la mise en place du fork local.

## Historique

| Date | Action | Commit |
|------|--------|--------|
| 2026-06-22 | Import Spriterrific 0.11.2 depuis PyPI | `94fdcfc` |
| 2026-06-22 | Nettoyage fork (`.gitignore`, suppression `test.txt` et tarball) | `7b90edb` |
| 2026-06-22 | Étape 1 : environnement local (en cours) | — |

## Étape 1 — Environnement local

### Fait

- [x] `uv` installé via Python 3.13 (`py -3.13 -m pip install uv`)
- [x] Dépendances installées : `py -3.13 -m uv sync`
  - `.venv` créé avec Python **3.13.0**
  - 31 paquets (spriterrific, fastapi, pillow, numpy, pytest, etc.)
- [x] CLI vérifiée : `py -3.13 -m uv run spriterrific --help`
- [x] `.env.example` créé (modèle pour les clés API)

### À finir

- [ ] Terminer `py -3.13 -m uv run pytest` (215 tests — interrompu en cours)
- [ ] Créer `.env` à partir de `.env.example` et renseigner les clés :
  - `FAL_KEY`
  - `FAL_API_KEY`
  - `REMOVE_BG_API_KEY`
- [ ] Committer `.env.example` (et pousser les commits locaux `7b90edb` + setup si souhaité)

### Commandes utiles

```powershell
cd c:\SpriterificMadHackAdemic\SpriterificMadHacademic

# Toujours utiliser Python 3.13 (le `python` par défaut est 3.10.8)
py -3.13 -m uv run spriterrific --help
py -3.13 -m uv run pytest

# Config API
copy .env.example .env
# puis éditer .env avec vos clés fal.ai
```

### Point d'attention

Sur cette machine :

- `python` → **3.10.8** (insuffisant, Spriterrific exige ≥ 3.11)
- `uv` n'est pas dans le PATH global → utiliser **`py -3.13 -m uv`**

## Étape 2 — Premier run (à venir)

Nécessite un `.env` rempli.

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
