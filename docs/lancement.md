# Lancer Spriterrific

Guide pratique pour **démarrer le logiciel** sur une machine déjà configurée. Pour l'installation initiale, voir [Installation](installation.md). Pour les clés API, voir [Clés API](cles-api.md).

---

## Avant de lancer

Depuis la racine du dépôt cloné :

```text
SpriterificMadHacademic/
  .venv/          ← créé par uv sync
  .env            ← copié depuis .env.example, avec FAL_KEY renseignée
```

| Vérification | Commande |
|--------------|----------|
| Environnement installé | `uv sync` (une fois par machine) |
| CLI accessible | `uv run spriterrific --help` |
| Clé FAL (génération IA) | variable `FAL_KEY` dans `.env` |

Sans `FAL_KEY`, les **outils locaux** (viewer, frame-picker, aligner, cleanup, pixel-snap) fonctionnent ; la génération image/vidéo via fal.ai échouera.

---

## Comment exécuter les commandes

Toutes les commandes partent du dossier du projet et utilisent l'environnement virtuel géré par `uv`.

### macOS / Linux

```bash
cd SpriterificMadHacademic
uv run spriterrific <commande> [options]
```

### Windows (PowerShell)

Si `python` pointe vers une version &lt; 3.11, préfixez avec le lanceur Python 3.13 :

```powershell
cd SpriterificMadHacademic
py -3.13 -m uv run spriterrific <commande> [options]
```

### Installation globale (sans clone)

Si Spriterrific est installé via `pipx`, `uv tool install` ou `pip`, appelez directement :

```bash
spriterrific <commande> [options]
```

(sans le préfixe `uv run`.)

---

## Trois façons de travailler

Spriterrific n'est pas une seule application avec un bouton « Démarrer ». C'est un **pipeline** composé de plusieurs points d'entrée selon l'étape du travail.

```text
┌─────────────────────────────────────────────────────────────────┐
│  Studio web (navigateur)     → bootstrap ancres (début rapide)  │
│  Interfaces graphiques (GUI) → ancres, curation, revue visuelle │
│  Ligne de commande (CLI)     → pipeline complet, automatisable  │
└─────────────────────────────────────────────────────────────────┘
```

| Mode | Idéal pour | Limites |
|------|------------|---------|
| **Studio web** | Créer une ancre front + W depuis le navigateur | Pas d'animations ni frame-picker intégrés |
| **GUI** | Revue visuelle, sélection de frames, retouches | Nécessite Tkinter |
| **CLI** | Workflow complet, scripts, CI, agents IA | Courbe d'apprentissage plus raide |

---

## 1. Studio web (interface navigateur)

Lance le serveur local FastAPI + formulaire web.

```bash
uv run uvicorn spriterrific.api:app --reload --port 8000
```

Ouvrir : [http://localhost:8000](http://localhost:8000)

Le serveur lit `.env` dans le répertoire courant. Détail des champs et de l'API : [Guide Studio](studio-readme.md).

Pour arrêter : `Ctrl+C` dans le terminal.

---

## 2. Interfaces graphiques (GUI)

Nécessitent **Tkinter** (inclus avec Python sur Windows/macOS ; sur Debian/Ubuntu : `sudo apt install python3-tk`).

Lancer depuis la racine du projet :

| Outil | Commande | Rôle |
|-------|----------|------|
| **Assistant ancres** | `uv run spriterrific anchor-wizard-gui` | Créer candidat + ancres N/S/E/W depuis texte ou image |
| **Navigateur de runs** | `uv run spriterrific viewer` | Parcourir les runs, prévisualiser sheets/GIF, ouvrir les autres outils |
| **Sélection de frames** | `uv run spriterrific frame-picker --run-dir runs/<run>` | Choisir les frames d'une vidéo extraite (walk, run…) |
| **Alignement** | `uv run spriterrific frame-aligner --input-dir <dossier>` | Décaler manuellement les frames 256×256 |
| **Nettoyage pixels** | `uv run spriterrific sprite-cleanup --sheet <fichier.png>` | Crayon, gomme, pipette sur une spritesheet ou des frames |

### Point d'entrée recommandé pour débuter en GUI

```bash
uv run spriterrific anchor-wizard-gui
```

ou, une fois des runs existants :

```bash
uv run spriterrific viewer
```

Le **viewer** peut cibler un run ou un projet de jeu :

```bash
uv run spriterrific viewer --run-dir runs/mon-heros-bootstrap
uv run spriterrific viewer --project-dir /chemin/vers/mon-jeu
```

---

## 3. Ligne de commande (CLI)

### Aide et découverte

```bash
uv run spriterrific --help
uv run spriterrific run --help
uv run spriterrific bootstrap-anchors --help
```

### Commandes de démarrage courantes

| Étape | Commande |
|-------|----------|
| Créer les ancres (texte ou image) | `uv run spriterrific bootstrap-anchors --character-id ... --source-prompt "..." --directions w --run-dir runs/...` |
| Lot d'animations image | `uv run spriterrific run-actions --actions idle,attack,hurt --reference ... --run-dir runs/...` |
| Une animation (image ou vidéo) | `uv run spriterrific run --action walk --direction w --reference ... --run-dir runs/... --mode video` |
| Traiter une sélection de frames | `uv run spriterrific process-selection --picker-dir ... --out-dir ...` |
| Finaliser pour le jeu | `uv run spriterrific finalize-runtime --input-dir ... --output-dir ...` |

Référence complète de toutes les options : [Commandes CLI](commandes-cli.md).

### Test sans appel API (dry run)

```bash
uv run spriterrific bootstrap-anchors ... --dry-fal
uv run spriterrific run ... --dry-fal
```

Utile pour vérifier les chemins et la configuration avant de consommer des crédits fal.ai.

---

## Parcours type : du lancement à l'export

### Parcours A — Débutant GUI + CLI

1. `uv run spriterrific anchor-wizard-gui` — créer et valider l'ancre.
2. `uv run spriterrific viewer --run-dir runs/<bootstrap>` — revoir les artefacts.
3. `uv run spriterrific run-actions ...` — générer idle, attack, hurt, etc.
4. `uv run spriterrific run --action walk --mode video ...` — générer la marche (nécessite **ffmpeg** installé sur le système).
5. `uv run spriterrific frame-picker --run-dir runs/<walk>` — sélectionner les frames.
6. `uv run spriterrific process-selection ...` — assembler la spritesheet.
7. `uv run spriterrific finalize-runtime ...` — marquer les assets prêts pour le moteur.

Détail pas à pas : [Tutoriel](tutoriel.md).

### Parcours B — Studio web uniquement (ancres)

1. `uv run uvicorn spriterrific.api:app --reload --port 8000`
2. Remplir le formulaire sur [http://localhost:8000](http://localhost:8000)
3. Consulter les artefacts dans `runs/api/` ou via le viewer.

Pour les animations, repasser en CLI ou GUI.

### Parcours C — Agent IA (Cursor / Claude / Codex)

Dans le projet de jeu :

```bash
cd votre-projet-de-jeu
uv run spriterrific skill install --target all
```

L'agent peut ensuite enchaîner les commandes CLI décrites dans le skill bundlé.

---

## Dépendances système selon l'usage

| Usage | Prérequis supplémentaire |
|-------|--------------------------|
| GUI (viewer, wizard, picker…) | Tkinter |
| Animations vidéo (walk, run) | **ffmpeg** dans le PATH |
| Génération IA live | `FAL_KEY` dans `.env` |
| Tests développeur | `uv run pytest` |

---

## Dépannage rapide

| Symptôme | Piste |
|----------|-------|
| `spriterrific: command not found` | Lancer depuis la racine du clone avec `uv run spriterrific`, ou exécuter `uv sync` |
| Erreur Python 3.10 ou inférieur | Utiliser Python ≥ 3.11 (`py -3.13` sur Windows) |
| GUI ne s'ouvre pas | Vérifier Tkinter ; sur Linux installer `python3-tk` |
| Échec extraction vidéo | Installer ffmpeg et vérifier `ffmpeg -version` |
| Erreur d'authentification fal.ai | Vérifier `FAL_KEY` dans `.env` à la racine du projet |
| Port 8000 déjà utilisé | Changer le port : `--port 8001` |

---

## Aller plus loin

| Document | Contenu |
|----------|---------|
| [Tutoriel](tutoriel.md) | Parcours complet zéro → personnage jouable |
| [Commandes CLI](commandes-cli.md) | Toutes les commandes et options |
| [Guide Studio](studio-readme.md) | API REST et formulaire web |
| [Guide opérateur](operator-guide.md) | Workflow production et promotion des assets |
| [Clés API](cles-api.md) | Configuration fal.ai |
