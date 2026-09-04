# Ressources tierces

Horizon lui-même est publié sous licence MIT — voir [LICENSE](LICENSE).

Le dépôt embarque en revanche des ressources écrites par d'autres, sous
`src/horizon/resources/`, et les redistribue telles quelles dans l'exécutable gelé. Leurs
licences respectives s'appliquent à ces fichiers, et leur texte intégral se trouve dans
[`licenses/`](licenses/).

| Fichier embarqué | Composant | Version | Licence |
|---|---|---|---|
| `JetBrainsMono-Regular.ttf` | [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) | 2.211 | [SIL OFL 1.1](licenses/OFL-1.1.txt) |
| `highlight.min.js`, `highlight-{csharp,dockerfile,powershell}.min.js`, `highlight-{dark,light}.min.css` | [highlight.js](https://github.com/highlightjs/highlight.js) | 11.9.0 | [BSD-3-Clause](licenses/highlightjs-BSD-3-Clause.txt) |
| `mermaid.min.js` | [Mermaid](https://github.com/mermaid-js/mermaid) | 11.14.0 | [MIT](licenses/mermaid-MIT.txt) |
| `horizon-editor.bundle.js` | [CodeMirror 6](https://codemirror.net/) et [Lezer](https://lezer.codemirror.net/) | voir ci-dessous | [MIT](licenses/codemirror-MIT.txt) |

## Détail du bundle de l'éditeur

`horizon-editor.bundle.js` est produit par esbuild à partir de
[`web/src/editor.js`](web/src/editor.js) ; ce n'est pas un fichier écrit à la main. Il
agrège les paquets déclarés dans [`web/package.json`](web/package.json), tous sous licence
MIT, aux versions figées par [`web/package-lock.json`](web/package-lock.json) :

`@codemirror/autocomplete`, `commands`, `lang-css`, `lang-html`, `lang-javascript`,
`lang-json`, `lang-markdown`, `lang-python`, `lang-sql`, `lang-xml`, `lang-yaml`,
`language`, `legacy-modes`, `lint`, `search`, `state`, `view` ; `@lezer/common`, `css`,
`highlight`, `html`, `javascript`, `json`, `lr`, `markdown`, `python`, `xml`, `yaml`.

Le copyright CodeMirror et Lezer est détenu par Marijn Haverbeke et les autres
contributeurs ; le texte MIT reproduit dans `licenses/codemirror-MIT.txt` couvre
l'ensemble de ces paquets.

## Thèmes de coloration syntaxique

`highlight-dark.min.css` et `highlight-light.min.css` sont les thèmes *GitHub Dark* et
*GitHub Light* distribués avec highlight.js, dérivés de
[primer/github-syntax-theme-generator](https://github.com/primer/github-syntax-theme-generator)
et couverts par la même licence BSD-3-Clause.

## Mise à jour

En remplaçant l'une de ces ressources, mettre à jour la version et la licence
correspondantes dans ce fichier. Les ressources sont volontairement vendorisées plutôt que
chargées depuis un CDN : l'application doit fonctionner hors ligne, et
`QWebEngineView` les lit par des URL `file://`.
