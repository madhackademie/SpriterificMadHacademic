# Guide Studio — Interface web locale

Le **Studio** Spriterrific est une interface web minimale pour lancer le workflow **bootstrap ancres** sans passer par la CLI. Il couvre aujourd'hui une partie du produit complet : la création d'ancre front + direction W.

> Pour le workflow complet (animations, frame-picker, export), utilisez la [CLI](tutoriel.md) ou le [viewer](commandes-cli.md#viewer).

## Important : serveur web, pas fenêtre bureau

Le Studio **n'ouvre pas de fenêtre logicielle** (contrairement à `anchor-wizard-gui` ou `viewer`).

| Ce que vous lancez | Ce qui se passe |
|--------------------|-----------------|
| `uvicorn spriterrific.api:app ...` | Un **serveur HTTP local** démarre dans le terminal |
| Console | Affiche des lignes `INFO:` (`Uvicorn running on http://127.0.0.1:8000`, etc.) — **c'est normal** |
| Interface utilisateur | S'ouvre **dans le navigateur** à [http://localhost:8000](http://localhost:8000) |

**Ne fermez pas le terminal** tant que vous utilisez le Studio. Pour arrêter le serveur : `Ctrl+C`.

Pour une **application bureau** (fenêtre Tkinter), voir [Lancer Spriterrific — GUI](lancement.md#2-interfaces-graphiques-gui).

## Démarrer le serveur

### macOS / Linux

```bash
cd SpriterificMadHacademic
uv run uvicorn spriterrific.api:app --reload --port 8000
```

### Windows (PowerShell)

```powershell
cd SpriterificMadHacademic
py -m uv run uvicorn spriterrific.api:app --reload --port 8000
```

(Si plusieurs versions Python sont installées : `py -3.14 -m uv run ...` ou `py -3.13 -m uv run ...`.)

Puis ouvrir manuellement dans le navigateur : [http://localhost:8000](http://localhost:8000) (ou [http://127.0.0.1:8000](http://127.0.0.1:8000)).

**Prérequis** : `.env` avec `FAL_KEY` dans le répertoire de travail (racine du clone).

## Ce que fait l'interface

Le formulaire **Bootstrap Front + W Anchor** envoie une requête `POST /bootstrap-anchors` et affiche :

| Panneau | Artefact |
|---------|----------|
| Source | Image source générée ou importée |
| Front | Candidat face (pixel-snapped) |
| West | Ancre profil W |

Les métadonnées (Run ID, liens bootstrap/review) s'affichent en bas. Le statut est pollé toutes les 3 secondes.

## Champs du formulaire

| Champ | Description |
|-------|-------------|
| Character | ID unique (`character-id`) |
| Run Label | Libellé du dossier run |
| Source Image Path | Chemin PNG local (optionnel si prompt) |
| Prompt | Description texte du personnage |
| Base Anchor | `front` (plateforme) ou `south` (top-down) |
| Directions | Directions à générer (ex. `w` ou `n,ne,e,se,s,sw,w,nw`) |
| K Colors | Palette pixel-snap (défaut 64) |
| Anchor Style | `lobit-v1` ou `high-fidelity-v1` |
| Anchor Snap | Pixel-snap activé ou non |
| Game View | platformer, top-down, generic |
| Asset Role | character, enemy, turret, prop, object |
| Anchor Context | Contexte caméra / jeu pour les prompts |
| Candidate Prompt | Override optionnel du prompt candidat |

## API REST

| Endpoint | Méthode | Rôle |
|----------|---------|------|
| `/` | GET | Interface web |
| `/health` | GET | Santé + versions |
| `/app-info` | GET | Versions SDK/CLI |
| `/bootstrap-anchors` | POST | Lance un job bootstrap (202 Accepted) |
| `/runs/{run_id}` | GET | Statut du job |
| `/runs/{run_id}/artifacts/{name}` | GET | Télécharger un artefact |

Artefacts exposés : `source`, `candidate-front`, `anchor-w`, `bootstrap-json`, `character-json`, `review`.

### Exemple curl

```bash
curl -X POST http://localhost:8000/bootstrap-anchors \
  -H "Content-Type: application/json" \
  -d '{
    "characterId": "test-hero",
    "sourcePrompt": "pixel art hero, neutral pose",
    "directions": "w",
    "gameView": "platformer",
    "kColors": 64
  }'
```

Les runs API sont écrits dans `runs/api/` par défaut.

## Limites actuelles

- Pas de génération d'animations dans le Studio web
- Pas de frame-picker intégré
- Pas d'orchestrateur multi-étapes avec approbations

Le chemin production recommandé reste :

```text
Studio ou CLI bootstrap → CLI run/run-actions → frame-picker → process-selection → finalize-runtime
```

## Outils GUI complémentaires (fenêtres bureau)

Ces commandes ouvrent une **fenêtre Windows/macOS/Linux** (Tkinter), pas le navigateur :

| Besoin | Commande |
|--------|----------|
| Parcourir tous les runs | `uv run spriterrific viewer` |
| Workflow ancres guidé | `uv run spriterrific anchor-wizard-gui` |
| Sélection frames | `uv run spriterrific frame-picker --run-dir runs/<run>` |

Sous Windows : préfixer avec `py -m uv run` (ex. `py -m uv run spriterrific viewer`).

Voir : [Lancer Spriterrific](lancement.md), [Tutoriel](tutoriel.md), [Guide opérateur](operator-guide.md).

## Dépannage Studio

| Symptôme | Cause / solution |
|----------|------------------|
| Seulement des logs `INFO:` dans la console, pas de fenêtre | **Normal** — ouvrir [http://localhost:8000](http://localhost:8000) dans le navigateur |
| Page blanche ou connexion refusée | Vérifier que le terminal affiche `Application startup complete` ; le serveur doit rester lancé |
| Port 8000 occupé | Changer le port : `--port 8001` puis ouvrir `http://localhost:8001` |
| Erreur fal.ai au submit | Vérifier `FAL_KEY` dans `.env` à la racine du projet |
