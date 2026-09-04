---
name: release
description: Publier une nouvelle version de Horizon — bump du numéro de version, PR, merge, tag et Release GitHub, dans l'ordre qui évite les incohérences. Utilise ce skill dès que l'utilisateur parle de sortir une version, monter le numéro de version, bumper la version, publier un exécutable, faire une release, poser un tag v*, ou demande « comment je passe en 0.2.0 » — même s'il ne mentionne ni tag ni release explicitement.
---

# Publier une version de Horizon

## Pourquoi l'ordre compte

Le numéro de version vit à un seul endroit dans le dépôt : `version` dans `pyproject.toml`.
Mais le workflow `.github/workflows/build.yml` a deux comportements :

| Contexte du build | Version utilisée |
|---|---|
| PR, ou push sur `main` | celle de `pyproject.toml` |
| push d'un tag `v*` | **celle du tag** — le TOML est ignoré |

C'est toute la difficulté. Sur un tag, le workflow n'ouvre jamais `pyproject.toml`, donc
rien ne signale que les deux divergent. Taguer `v0.2.0` sans avoir bumpé produit un
`Horizon-0.2.0-win64.zip` dont les métadonnées de paquet disent encore `0.1.0`, et personne
ne s'en aperçoit avant longtemps.

D'où la règle : **le TOML d'abord, mergé, puis le tag** — et le tag sur le commit de merge
dans `main`, jamais sur la branche de feature. Un tag est une étiquette permanente sur un
commit précis ; si tu tagues la branche avant le merge, tu désignes un commit qui n'est pas
celui que `main` recevra (avec un squash merge, il n'y entre même jamais).

## Avant de commencer

L'utilisateur n'est pas forcément à l'aise avec les tags. Explique ce que tu fais au fur et
à mesure plutôt que d'enchaîner les commandes en silence, et ne saute pas les points d'arrêt
même si tout se passe bien.

Vérifie l'état de départ et signale tout ce qui cloche avant d'agir :

```bash
git status --short && git log --oneline -1 origin/main && gh release list --limit 3
```

- **Arbre de travail sale** : demande quoi en faire. Ne commite jamais des changements que
  l'utilisateur n'a pas mentionnés — `.claude/settings.local.json` traîne souvent modifié.
- **Version actuelle** : lis `version` dans `pyproject.toml`.
- **Tag déjà existant** : `git ls-remote --tags origin` — si le numéro visé existe déjà,
  arrête-toi et propose le suivant.

## Choisir le numéro

Le projet est en `0.x`, donc l'API n'est pas figée. Propose un numéro, explique pourquoi,
et laisse l'utilisateur trancher :

- **patch** (`0.1.0` → `0.1.1`) — corrections de bugs uniquement ;
- **mineure** (`0.1.0` → `0.2.0`) — nouvelles fonctionnalités ou changement de comportement ;
- **majeure** (`1.0.0`) — le jour où le schéma de base et l'API HTTP ne bougeront plus sans
  préavis. Ne le propose pas de toi-même, c'est une décision de produit.

Pour choisir, regarde ce qui a été mergé depuis le dernier tag :

```bash
git log --oneline $(git describe --tags --abbrev=0 2>/dev/null || echo HEAD)..origin/main
```

## Les étapes

### 1. Brancher depuis main

```bash
git checkout main && git pull origin main && git checkout -b release/v<VERSION>
```

### 2. Bumper le TOML

Modifie la seule ligne `version = "..."` de `pyproject.toml`. Rien d'autre : aucun code ne
lit cette valeur, `src/horizon/__init__.py` est vide et il n'y a pas de `__version__`.

Commite avec le style du dépôt — préfixe conventionnel, message en français :

```
chore: passer en version <VERSION>
```

### 3. Ouvrir la PR

Pousse la branche et ouvre la PR contre `main`. Dans la description, liste ce que la version
apporte : le contenu de la Release en découlera, et c'est le seul endroit où quelqu'un lira
un résumé écrit par un humain.

### 4. Attendre le CI

Le check s'appelle **Build Windows** et prend environ 3 min 30. Surveille-le sans faire
tourner l'utilisateur en boucle.

Ce build est informatif : l'artefact produit s'appelle déjà `Horizon-<VERSION>-win64.zip`,
ce qui confirme que le bump a bien été pris en compte **avant** de taguer quoi que ce soit.
Signale-le à l'utilisateur, c'est sa vérification gratuite.

Si le run est rouge, arrête la release : corrige sur la branche et relance. Ne merge jamais
un check rouge. Vérifie si une règle de protection couvre `main` — si oui elle t'arrêtera,
sinon rien ne t'en empêchera techniquement et la discipline t'incombe entièrement.

### 5. — POINT D'ARRÊT — Merger

**Demande confirmation avant de merger.** C'est le premier geste irréversible.

Résume ce qui va être mergé et attends un accord explicite. Une fois d'accord, merge, puis
reviens sur `main` à jour.

### 6. — POINT D'ARRÊT — Taguer et pousser

**Demande confirmation avant de pousser le tag.** Pousser le tag publie une Release
GitHub visible ; c'est le point de non-retour.

Vérifie d'abord que `main` contient bien le bump :

```bash
git checkout main && git pull origin main && grep '^version' pyproject.toml
```

Puis crée un tag **annoté** (`-a`) : il porte auteur, date et message, contrairement à un
tag léger qui n'est qu'un pointeur anonyme.

```bash
git tag -a v<VERSION> -m "Horizon v<VERSION>"
```

Et pousse-le explicitement — `git push` seul n'envoie pas les tags, c'est le piège classique :

```bash
git push origin v<VERSION>
```

### 7. Vérifier la publication

Le push du tag déclenche un run complet : `build` (~3 min 30) puis `release` (~30 s), ce
dernier n'existant que sur les tags. Confirme le résultat à l'utilisateur :

```bash
gh release view v<VERSION> --json tagName,isDraft,assets --jq '"\(.tagName) — brouillon: \(.isDraft)", (.assets[] | "  \(.name) — \(.size/1048576|floor) Mo")'
```

Un zip d'environ 210 Mo doit être attaché. Si l'asset manque alors que le job `release` est
vert, regarde les logs de ce job : c'est le seul endroit où le zip transite entre un runner
Windows et un runner Ubuntu.

## Quand ça se passe mal

**Le CI échoue après le bump.** Le problème est presque toujours réel, pas un caprice de CI —
il a déjà attrapé un import manquant et une dépendance non bornée. Lis les logs avant de
relancer.

**Tag créé mais pas encore poussé.** `git tag -d v<VERSION>`, sans conséquence.

**Tag déjà poussé, à tort.** Ne le supprime pas. D'autres l'ont peut-être récupéré, et
supprimer un tag publié transforme la Release associée en brouillon. Passe au numéro suivant :
les tags sont bon marché, en gaspiller un coûte moins cher que de réécrire une référence
publique. Ne propose la suppression que si l'utilisateur insiste, en expliquant le risque.

**Le TOML et le tag divergent.** Si c'est déjà publié, le plus propre est de bumper le TOML
à la valeur du tag dans une PR de correction, plutôt que de retoucher le tag.
