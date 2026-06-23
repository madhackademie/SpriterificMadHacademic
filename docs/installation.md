# Installation

Guide d'installation du fork **SpriterificMadHacademic** sur une machine Windows, macOS ou Linux.

## Prérequis

| Composant | Version | Notes |
|-----------|---------|-------|
| Python | **≥ 3.11** (recommandé **3.13**) | Sur Windows, `python` peut être 3.10 — utiliser `py -3.13` |
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
# Installer Python 3.13 depuis python.org si nécessaire
py -3.13 -m pip install uv
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
py -3.13 -m uv run spriterrific --help

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

## Outils GUI

Les interfaces graphiques nécessitent **Tkinter** (souvent inclus avec Python).

| Outil | Commande |
|-------|----------|
| Assistant ancres | `uv run spriterrific anchor-wizard-gui` |
| Navigateur de runs | `uv run spriterrific viewer` |
| Sélection de frames | `uv run spriterrific frame-picker --run-dir ...` |
| Alignement | `uv run spriterrific frame-aligner --input-dir ...` |
| Nettoyage pixels | `uv run spriterrific sprite-cleanup --sheet ...` |

Sur Linux sans Tkinter : `sudo apt install python3-tk` (Debian/Ubuntu).

---

## Interface web (Studio)

```bash
uv run uvicorn spriterrific.api:app --reload --port 8000
```

Ouvrir [http://localhost:8000](http://localhost:8000). Voir [studio-readme.md](studio-readme.md).

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
