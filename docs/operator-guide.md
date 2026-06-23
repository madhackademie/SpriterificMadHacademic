# Guide opérateur — Production et revue

Ce guide s'adresse à l'opérateur qui **supervise** la qualité des assets : enseignant, lead art, ou vous-même en relecture.

## Rôle de l'opérateur

Spriterrific est en **alpha** : l'IA propose, l'humain valide. Quatre verrous qualité :

1. **Choix d'ancre** — silhouette, costume, palette, proportions
2. **Sélection de frames** — fluidité, pas de frames aberrantes
3. **Alignement** — pas de « pop » entre frames
4. **Promotion finale** — `finalize-runtime` + copie jeu

Ne sautez aucun verrou pour un asset destiné à la production.

## Workflow standard

```text
┌─────────────────┐
│ bootstrap-anchors│ ← REVUE 1 : candidat + ancre W
└────────┬────────┘
         ▼
┌─────────────────┐
│ run-actions     │ ← REVUE 2 : chaque action image
│ run (video)     │ ← REVUE 2b : preview vidéo brute
└────────┬────────┘
         ▼
┌─────────────────┐
│ frame-picker    │ ← REVUE 3 : cycle walk/run
└────────┬────────┘
         ▼
┌─────────────────┐
│process-selection│ ← REVUE 4 : spritesheet runtime
└────────┬────────┘
         ▼
┌─────────────────┐
│ frame-aligner   │ ← REVUE 5 (optionnel) : micro-ajustements
│ sprite-cleanup  │
└────────┬────────┘
         ▼
┌─────────────────┐
│finalize-runtime │ ← GATE : publicAssetReady
└────────┬────────┘
         ▼
    Copie vers jeu
```

## Pages de revue

Chaque run sérieux produit `review/index.md` ou `review/bootstrap/index.md`. Ouvrez-les dans un éditeur Markdown ou via le viewer.

Contenu attendu :
- avant / après chaque transformation
- commande suggérée pour l'étape suivante
- avertissements (palette, fringe cleanup, coercition de frames)

## Checklist ancre

- [ ] Silhouette lisible à 256×256
- [ ] Pas de membres coupés
- [ ] Fond chroma uniforme (pas de damier faux transparent)
- [ ] Palette cohérente avec le style visé
- [ ] Direction correcte pour le jeu (W = profil gauche plateforme)
- [ ] Hauteur native snap ~100–130 px pour `lobit-v1`

Si l'ancre échoue : relancer bootstrap avec prompt affiné ou `accept-anchor` après correction manuelle.

## Checklist animation image

- [ ] Chaque pose lisible dans sa cellule 256×256
- [ ] Pas de débordement d'arme/cape sur cellule voisine non récupérée
- [ ] Timing FPS cohérent entre actions similaires
- [ ] `manifest.json` présent dans export

## Checklist animation vidéo

- [ ] Pas d'ombre portée ou ligne de sol dans les frames source
- [ ] Identité costume préservée vs ancre
- [ ] Cycle walk/run boucle sans à-coup (frame picker)
- [ ] Pas de frame dupliquée ou floue dans la sélection
- [ ] Preview `preserve-canvas` consultée avant curation

## Checklist promotion

- [ ] `finalize-runtime` exécuté
- [ ] `publicAssetReady: true` dans manifest
- [ ] `finalize-runtime.json` présent
- [ ] GIF preview relu en boucle
- [ ] Spritesheet : pieds alignés entre idle/walk/attack (sauf jump)

## Gestion des échecs courants

| Symptôme | Action opérateur |
|----------|------------------|
| Costume qui change | Reprendre depuis ancre ; clip vidéo plus court ; autre seed |
| Vert sur vert (matte) | `--chroma "#FF00FF"` sur tout le pipeline |
| Trop de pixels matte supprimés | Vérifier `fringe-metadata.json` ; changer matte ou `--no-green-fringe-cleanup` |
| Walk trop rapide | `--fps` plus bas ; `--action-context` plus explicite |
| Échelle qui dérive | Créer `size-contract` depuis idle validé |

## Branches d'export multiples

Le viewer permet de comparer :
- `export/` — preview automatique
- `frame-picker/<ts>/post-selection/<ts>/export/` — curation manuelle

Toujours promouvoir la branche **curatée**, pas la preview automatique pour walk/run.

## Organisation atelier (MadHackademie)

Recommandations :
- Un dossier `runs/` par binôme ou par personnage
- `.env` partagé en salle via gestionnaire de secrets (pas sur Git)
- Nommage : `--character-id prenom-personnage` ou `equipe-01-heros`
- Conserver les runs ratés pour analyse pédagogique
- Copier uniquement `final/` vers le dépôt du jeu

## Commandes opérateur rapides

```bash
# Vue d'ensemble
uv run spriterrific viewer

# Valider un export
uv run spriterrific validate --run-dir runs/...

# Métadonnées run
uv run spriterrific inspect --run-dir runs/...

# Corriger franges sans regénérer
uv run spriterrific despill --sheet path/spritesheet.png --chroma "#00FF00"
```

## Ce qui n'est pas encore automatisé

- Orchestrateur produit unique bout-en-bout
- Approbations API entre étapes
- `run-actions` parallèle
- Studio web complet (animations intégrées)

Planifiez des **étapes CLI manuelles** pour l'instant.

Voir : [Tutoriel](tutoriel.md), [workspace-contract.md](workspace-contract.md).
