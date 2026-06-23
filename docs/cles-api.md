# Clés API et services IA

Ce guide explique **quelles clés** Spriterrific utilise, **à quoi elles servent**, et **comment les obtenir**.

## Résumé

| Clé | Obligatoire ? | Service | Usage dans Spriterrific |
|-----|---------------|---------|-------------------------|
| `FAL_KEY` ou `FAL_API_KEY` | **Oui** pour génération live | [fal.ai](https://fal.ai) | Images (ancres, pose boards), vidéos (walk/run), suppression de fond Bria |
| `REMOVE_BG_API_KEY` | Non | — | Documentée upstream ; **non utilisée** par le code actuel |

Sans clé FAL, vous pouvez encore utiliser les outils **locaux** (frame-picker, aligner, cleanup, pixel-snap sur images existantes), mais pas la génération IA automatique.

---

## FAL_KEY / FAL_API_KEY (fal.ai)

### À quoi ça sert

fal.ai est le **fournisseur principal** de Spriterrific. Via cette plateforme, le pipeline appelle :

**Génération d'images** (ancres, candidats, pose boards) :
- `gpt-image-2` (défaut) — text-to-image et image-to-image
- Alternatives : Grok Imagine, Nano Banana, GPT Image 1.5 (voir `model-presets.json`)

**Génération vidéo** (marche, course, actions vidéo) :
- `grok-imagine-video-i2v` (défaut) — image-to-video court
- `wan-2.7` — transitions avec image de fin (`get_up`, etc.)
- `wan-2.2-a14b-i2v-turbo`, `seedance-2.0-i2v`, et autres (expérimental)

**Suppression de fond** (mode `--bg-remove bria`) :
- API Bria via fal.ai (`fal-ai/bria/background/remove`)

### Où obtenir la clé

1. Créer un compte sur [https://fal.ai](https://fal.ai)
2. Aller dans [Dashboard → Keys](https://fal.ai/dashboard/keys)
3. Créer une clé API
4. Copier la valeur dans votre fichier `.env` :

```text
FAL_KEY=votre_cle_ici
```

`FAL_API_KEY` est un **alias** accepté — une seule des deux variables suffit.

### Coûts et crédits

- fal.ai fonctionne avec un **système de crédits** (pay-as-you-go ou abonnement selon l'offre).
- Chaque génération image ou vidéo consomme des crédits ; le montant dépend du modèle et de la durée.
- Pour un **atelier pédagogique**, prévoir un budget test (quelques euros suffisent pour un premier personnage avec 4–6 animations).
- Consultez [fal.ai/pricing](https://fal.ai/pricing) pour les tarifs actuels.

### Bonnes pratiques

- **Ne jamais** committer `.env` sur GitHub (déjà dans `.gitignore`).
- Partager les clés entre étudiants uniquement via un canal sécurisé (pas par email en clair si possible).
- Utiliser `--dry-fal` pour tester la pipeline **sans appel API** (génère la structure de run, pas les images).
- Surveiller la consommation dans le dashboard fal.ai.

---

## REMOVE_BG_API_KEY

Cette variable apparaît dans le README upstream et est tracée dans les logs (`envPresent`), mais **aucun module du code ne l'utilise actuellement**.

La suppression de fond se fait par :
- **`chroma`** (défaut en mode image) — keying local sur la couleur matte (`#00FF00` par défaut)
- **`bria`** — via fal.ai, donc `FAL_KEY` suffit
- **`none`** — pas de suppression

Vous pouvez ignorer `REMOVE_BG_API_KEY` pour l'instant.

---

## Configuration du fichier `.env`

À la racine du projet (là où vous lancez `spriterrific`) :

```powershell
copy .env.example .env
# Éditer .env avec un éditeur de texte
```

Exemple minimal :

```text
FAL_KEY=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Spriterrific charge automatiquement `.env` au premier appel provider (voir `commands.py`). Les variables déjà définies dans le shell ne sont pas écrasées.

---

## Mode sans clé API (hybride)

Si vous n'avez pas de clé FAL :

| Étape | Possible sans FAL ? |
|-------|---------------------|
| Générer images avec un autre outil (DALL·E, Midjourney, imagegen Codex…) | Oui — sauvegarder les PNG et les passer à Spriterrific |
| `bootstrap-anchors --source-image` + pixel-snap | Oui (sans étape générative candidate) |
| `run-actions --existing-sheet-root` | Oui si vous fournissez les pose boards |
| Walk / run vidéo | **Non** — nécessite un provider vidéo (FAL par défaut) |
| Frame-picker, aligner, cleanup, finalize | Oui — outils 100 % locaux |

---

## Variables avancées (API / déploiement)

Réservées au déploiement serveur (Railway, etc.) — **pas nécessaires en local** :

| Variable | Défaut | Rôle |
|----------|--------|------|
| `SPRITERRIFIC_API_RUN_ROOT` | `runs/api` | Dossier des runs API |
| `SPRITERRIFIC_SDK_VERSION` | version package | Métadonnées |
| `SPRITERRIFIC_CLI_VERSION` | version package | Métadonnées |
| `RAILWAY_*` | — | Infos déploiement Railway |

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `FAL_KEY or FAL_API_KEY is required` | Créer `.env` à la racine du répertoire de travail |
| Génération échoue avec 401/403 | Vérifier la clé sur fal.ai ; crédits épuisés ? |
| `.env` ignoré | Lancer les commandes depuis le dossier contenant `.env` |
| Personnage vert sur fond vert | Changer la matte : `--chroma "#FF00FF"` partout |

Voir aussi : [Tutoriel](tutoriel.md), [Installation](installation.md).
