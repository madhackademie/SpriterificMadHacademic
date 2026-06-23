# Guide Studio — Interface web locale

Le **Studio** Spriterrific est une interface web minimale pour lancer le workflow **bootstrap ancres** sans passer par la CLI. Il couvre aujourd'hui une partie du produit complet : la création d'ancre front + direction W.

> Pour le workflow complet (animations, frame-picker, export), utilisez la [CLI](tutoriel.md) ou le [viewer](commandes-cli.md#viewer).

## Démarrer le serveur

```bash
cd SpriterificMadHacademic
uv run uvicorn spriterrific.api:app --reload --port 8000
```

Ouvrir : [http://localhost:8000](http://localhost:8000)

**Prérequis** : `.env` avec `FAL_KEY` dans le répertoire de travail.

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

## Outils GUI complémentaires

| Besoin | Outil |
|--------|-------|
| Parcourir tous les runs | `spriterrific viewer` |
| Workflow ancres guidé | `spriterrific anchor-wizard-gui` |
| Sélection frames | `spriterrific frame-picker` |

Voir : [Tutoriel](tutoriel.md), [Guide opérateur](operator-guide.md).
