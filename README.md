# Meta Hebdo 40K (AJA)

Chaque lundi à 9h (heure de Paris), ce projet relève tout seul les résultats Warhammer 40K du week-end sur [listhammer.info](https://listhammer.info/stats), fabrique une page de récap pensée pour le téléphone et poste le lien sur le Discord de l'AJA.

- **La page de la semaine** (toujours la même adresse) : https://florianmartinezlopez.github.io/meta-hebdo-aja/
- **Les semaines passées** : https://florianmartinezlopez.github.io/meta-hebdo-aja/archives/

Rien à faire de ton côté : ça tourne sur GitHub, même ordinateur éteint, gratuitement.

## Changer les armées de l'AJA

Tout est dans [`config/team.json`](config/team.json). Pour ajouter ou retirer une armée :

1. Ouvre le fichier sur GitHub et clique sur le crayon (Modifier).
2. Copie une ligne existante et change `nom` (nom exact de la faction sur Listhammer), `court` (nom raccourci pour Discord), `slug` (la fin de l'adresse `listhammer.info/factions/...`) et les deux couleurs (`couleur` pour le thème clair, `couleur_sombre` pour le thème sombre).
3. Clique sur « Commit changes ». Le changement sera pris en compte lundi prochain (ou tout de suite si tu relances à la main).

La liste des 28 factions suivies est dans [`config/factions.json`](config/factions.json) : à toucher seulement si Listhammer ajoute une faction.

## Relancer le récap à la main

GitHub > le repo > onglet **Actions** > **Récap hebdo** (à gauche) > bouton **Run workflow**. Décoche « Poster le message sur Discord » si tu veux juste rafraîchir la page sans prévenir l'équipe.

## Si ça casse

- En cas d'échec, la page en ligne **n'est pas remplacée** (celle de la semaine d'avant reste visible) et le Discord reçoit : « Récap de la semaine indisponible, le relevé Listhammer a échoué. »
- Pour comprendre : onglet **Actions**, clique sur l'exécution en rouge, puis sur l'étape en rouge. Le message commence par `ÉCHEC DU RELEVÉ`, `ÉCHEC DE LA GÉNÉRATION` ou `ÉCHEC DU TEST D'AFFICHAGE`. Copie-le dans Claude Code dans ce dossier : il saura corriger.
- Cause la plus probable : Listhammer a changé la structure de ses pages.

## Comment ça marche

| Étape | Fichier | Ce qu'il fait |
|---|---|---|
| Relevé | `scripts/releve.py` | Lit `/stats` et les 28 pages factions de Listhammer (données intégrées aux pages, une requête toutes les 2,5 s, robots.txt respecté) |
| Calculs et page | `scripts/construire.py` | Calcule classements, archétypes émergents, phrases d'analyse, et écrit la page |
| Test | `scripts/verifier_affichage.py` | Vérifie la page à 380 px (clair et sombre) et en grand écran : pas de défilement horizontal, menu burger fonctionnel |
| Discord | `scripts/discord.py` | Poste le message court via le webhook |
| Automatisation | `.github/workflows/recap-hebdo.yml` | Enchaîne le tout chaque lundi |

Les données de chaque semaine sont gardées dans `data/AAAA-Wss/` (`stats.json`, `factions/<slug>.json`, `lists.csv`, `discord.txt`). C'est cet historique qui permet de repérer les archétypes émergents ou en recul d'une semaine sur l'autre.

Les phrases d'analyse sont des gabarits remplis par les chiffres : aucun chiffre n'est inventé.

### Ce que Listhammer ne permet pas

- Le **win rate par faction et par force de disposition** n'est pas publié, et les pages tournoi (qui donneraient les appariements) sont interdites à la lecture automatique par le robots.txt du site. Ce tableau n'est donc pas affiché.
- Les pages joueurs sont elles aussi interdites à la lecture : la page se contente d'y faire des liens.

## Secrets

Le seul secret est l'adresse du webhook Discord, rangée dans GitHub (Settings > Secrets and variables > Actions > `DISCORD_WEBHOOK_URL`). Elle n'apparaît dans aucun fichier. Le repo est public : n'y écris jamais de mot de passe ou d'adresse de webhook.

## Faire tourner en local (pour Claude Code)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium
python3 scripts/releve.py            # affiche la semaine, ex. 2026-W42
python3 scripts/construire.py 2026-W42
.venv/bin/python scripts/verifier_affichage.py docs/index.html captures
```
