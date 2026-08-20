# Bundled fonts

Two families, five `woff2` files, ~120 kB total. Committed as **static assets,
not npm packages** (D21 decision 10): nothing here is resolved from a registry
at runtime, and nothing is fetched from a CDN — which the container could not
reach anyway, and which would leak a request per visitor to a third party.

| File | Family | Weight | Used for |
|---|---|---|---|
| `inter-400.woff2` | Inter | 400 | body text |
| `inter-500.woff2` | Inter | 500 | table headers, labels, nav |
| `inter-600.woff2` | Inter | 600 | headings, metric values |
| `jetbrains-mono-400.woff2` | JetBrains Mono | 400 | ids, chunk refs, model names, JSON |
| `jetbrains-mono-500.woff2` | JetBrains Mono | 500 | emphasised technical values |

Latin subsets only. The UI is English-only (i18n is out of scope for the MVP),
and the full character sets are roughly four times the size for glyphs nothing
renders.

## Licensing

Both are **SIL Open Font License 1.1**, which permits bundling and
redistribution in a product provided the license travels with the fonts and the
fonts are not sold on their own. Neither condition is a constraint here.

- Inter — Rasmus Andersson, <https://github.com/rsms/inter> (OFL-1.1)
- JetBrains Mono — JetBrains, <https://github.com/JetBrains/JetBrainsMono> (OFL-1.1)

Retrieved from the Fontsource CDN (`cdn.jsdelivr.net/fontsource`) on
2026-08-16, which repackages the upstream releases without modifying the
outlines.

## Replacing or adding a weight

`@font-face` declarations live in `frontend/src/styles/tokens.css`. Add the
file here, declare it there, and keep `font-display: swap` — a blocked font
should delay glyphs, never the screen.
