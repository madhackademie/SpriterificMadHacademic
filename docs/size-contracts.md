# Contrats de taille (size contracts)

Un **contrat de taille** verrouille l'échelle, la largeur max, le centre horizontal et la ligne de pied d'un personnage pour que les animations suivantes restent cohérentes.

## Problème résolu

Les modèles vidéo font dériver :
- la taille du personnage
- la position verticale (pieds qui flottent ou s'enfoncent)
- la largeur (armes, capes)

Le contrat injecte des contraintes dans les prompts et valide les exports.

## Créer un contrat

Depuis un asset **déjà approuvé** (idle, ancre runtime, etc.) :

```bash
uv run spriterrific size-contract \
  --source public/assets/characters/heros/idle/spritesheet.png \
  --out characters/heros/size-contract.json \
  --action idle \
  --direction w \
  --pivot foot-center
```

Pivots :
- `foot-center` — humanoïdes (défaut plateforme)
- `base-center` — tourelles, ennemis plantés

## Utiliser le contrat

**Génération vidéo** :

```bash
uv run spriterrific run \
  --action walk \
  ... \
  --size-contract characters/heros/size-contract.json
```

**Post-traitement** :

```bash
uv run spriterrific process-selection \
  ... \
  --size-contract characters/heros/size-contract.json
```

Les champs non spécifiés sur la CLI sont remplis depuis le contrat. Un `size-contract-audit.json` est écrit.

## Mode strict

```bash
--size-contract-strict
```

Échoue si l'audit détecte une dérive significative (au lieu d'un simple avertissement).

## Ce que le contrat ne fait pas

- Il ne corrige pas une mauvaise génération
- Il ne masque pas une identité de costume dégradée
- Il ne remplace pas la revue humaine

Utilisez-le comme **garde-fou** après une première animation de référence validée.

## Audit

```bash
uv run spriterrific audit-size-contract \
  --source runs/.../export/spritesheet.png \
  --contract characters/heros/size-contract.json
```

Voir : [walk-cycle-video-pipeline.md](walk-cycle-video-pipeline.md).
