# Documentation Spriterrific — MadHackademie

Index de la documentation du fork [SpriterificMadHacademic](https://github.com/madhackademie/SpriterificMadHacademic).

## Démarrage rapide

| Document | Public | Description |
|----------|--------|-------------|
| [Tutoriel complet](tutoriel.md) | Débutants | Parcours pas à pas : installation → premier personnage → animations → export jeu |
| [Installation](installation.md) | Tous | Prérequis, clone, `uv sync`, tests, configuration par machine |
| [Lancer le logiciel](lancement.md) | Tous | Studio web, GUI, CLI : comment démarrer chaque outil |
| [Clés API et services IA](cles-api.md) | Tous | Quelles clés, où les obtenir, coûts, sécurité |

## Guides d'utilisation

| Document | Description |
|----------|-------------|
| [Référence des commandes CLI](commandes-cli.md) | Toutes les commandes `spriterrific` avec exemples |
| [Guide Studio (interface web)](studio-readme.md) | Serveur local + navigateur (pas de fenêtre bureau) ; bootstrap ancres |
| [Guide opérateur](operator-guide.md) | Workflow production, revue, promotion des assets |

## Pipelines techniques

| Document | Description |
|----------|-------------|
| [Pipeline spritesheet image](imagegen-spritesheet-pipeline.md) | Actions statiques (idle, attack, hurt…) via pose boards |
| [Pipeline marche / vidéo](walk-cycle-video-pipeline.md) | Walk, run et cycles vidéo image-to-video |
| [Contrats de taille](size-contracts.md) | Garder la même échelle entre animations |
| [Contrat d'espace de travail](workspace-contract.md) | Dossiers `runs/`, métadonnées, promotion |

## Autres

| Document | Description |
|----------|-------------|
| [CHANGELOG](../CHANGELOG.md) | Historique des versions |
| [SETUP MadHackademie](../SETUP-MADHACKADEMIE.md) | Notes de progression du fork |
| [README principal](../README.md) | Vue d'ensemble upstream (anglais) |
| [Skill agent](../src/spriterrific/skills/spriterrific/SKILL.md) | Instructions pour agents IA (Claude, Cursor, Codex) |

## Chemin recommandé pour un atelier

1. Lire [Installation](installation.md) et configurer [les clés API](cles-api.md).
2. Consulter [Lancer le logiciel](lancement.md) pour choisir Studio, GUI ou CLI.
3. Suivre le [Tutoriel](tutoriel.md) de bout en bout sur un personnage test.
4. Consulter [commandes-cli.md](commandes-cli.md) pour aller plus loin.
5. Installer le skill agent dans le projet de jeu : `spriterrific skill install --target all`.
