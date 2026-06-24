# Installation

Guide d'installation du fork **SpriterificMadHacademic** sur une machine Windows, macOS ou Linux.

## Prérequis

| Composant | Version | Notes |
|-----------|---------|-------|
| Python | **≥ 3.11** (recommandé **3.13** ou **3.14**) | Sur Windows, utiliser le lanceur `py` : `py -m uv run ...` |
| Git | récent | Pour cloner le dépôt |
| `uv` | récent | Gestionnaire d'environnement (recommandé) |

Spriterrific **ne s'installe pas une fois pour toutes sur GitHub** : le code est versionné, mais chaque poste recrée son environnement local (`.venv`) et son `.env`.

---

## 1. Cloner le dépôt

```bash
git clone https://github.com/madhackademie/SpriterificMadHacademic.git
cd SpriterificMadHacademic
```

---

## 2. Installer Python et uv

### Windows

```powershell
# Installer Python ≥ 3.11 depuis python.org (cocher « tcl/tk and IDLE » pour la GUI)
py -m pip install uv
# ou, si plusieurs versions : py -3.14 -m pip install uv
```

### macOS / Linux

```bash
# Python 3.12+ via le gestionnaire de paquets, puis :
pip install uv
# ou : curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 3. Installer les dépendances

```bash
uv sync
```

Cela crée `.venv/` et installe spriterrific, Pillow, FastAPI, pytest, etc. (verrouillé par `uv.lock`).

### Vérifier la CLI

```bash
# Windows
py -m uv run spriterrific --help

# macOS / Linux
uv run spriterrific --help
```

---

## 4. Configurer les clés API

```bash
cp .env.example .env
```

Éditer `.env` et renseigner `FAL_KEY` (voir [cles-api.md](cles-api.md)).

---

## 5. Lancer les tests (optionnel)

```bash
uv run pytest
```

Environ **215 tests**. Certains tests pixel-snap appellent `uv` en sous-processus — `uv` doit être dans le PATH ou installé comme module Python (`py -3.13 -m uv`).

---

## Installation alternative (sans clone)

Pour utiliser Spriterrific **sans le fork** MadHackademie :

```bash
pipx install spriterrific
# ou
uvx spriterrific --help
```

Pour les ateliers MadHackademie (branding, docs FR, presets futurs), préférez le **clone Git**.

---

## Outils GUI (fenêtres bureau)

Les interfaces graphiques ouvrent une **fenêtre application** (Tkinter). Ce n'est **pas** le Studio web (voir section suivante).

| Outil | Commande (Windows) |
|-------|-------------------|
| Assistant ancres | `py -m uv run spriterrific anchor-wizard-gui` |
| Navigateur de runs | `py -m uv run spriterrific viewer` |
| Sélection de frames | `py -m uv run spriterrific frame-picker --run-dir ...` |
| Alignement | `py -m uv run spriterrific frame-aligner --input-dir ...` |
| Nettoyage pixels | `py -m uv run spriterrific sprite-cleanup --sheet ...` |

Sur Linux sans Tkinter : `sudo apt install python3-tk` (Debian/Ubuntu).

Sur Windows, si `Can't find a usable init.tcl` : réinstaller Python avec **tcl/tk** coché ; ne pas laisser `TCL_LIBRARY` / `TK_LIBRARY` pointer vers une autre version de Python.

---

## Interface web (Studio) — serveur local

Le Studio **ne ouvre pas de fenêtre bureau**. La commande démarre un **serveur web** ; l'interface s'affiche dans le **navigateur**.

```powershell
# Windows
py -m uv run uvicorn spriterrific.api:app --reload --port 8000

# macOS / Linux
uv run uvicorn spriterrific.api:app --reload --port 8000
```

La console affiche des lignes `INFO:` (`Uvicorn running on http://127.0.0.1:8000`) — c'est normal. Ouvrir ensuite [http://localhost:8000](http://localhost:8000). Laisser le terminal ouvert ; `Ctrl+C` pour arrêter.

Voir [studio-readme.md](studio-readme.md).

---

## Skill agent (Cursor / Claude / Codex)

Dans un projet de jeu :

```bash
cd votre-projet-de-jeu
uv run spriterrific skill install --target all
```

Installe les instructions dans `.claude/skills/`, `.codex/skills/`, `.agents/skills/`.

---

## Structure après installation

```text
SpriterificMadHacademic/
  .venv/              # environnement local (gitignored)
  .env                # clés API (gitignored)
  .env.example        # modèle versionné
  docs/               # documentation
  src/spriterrific/   # code source
  tests/
  runs/               # sorties de génération (gitignored, créé à l'usage)
```

---

## Prochaine étape

→ [Lancer le logiciel](lancement.md) — Studio web, GUI et CLI  
→ [Tutoriel complet](tutoriel.md)
