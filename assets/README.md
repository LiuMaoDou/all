# Bundled assets

These files are served locally so the UI does not depend on third-party asset requests.

- `lucide/icons.json`: 45 SVGs from [lucide-static 1.59.0](https://www.npmjs.com/package/lucide-static/v/1.59.0), distributed in its [official package archive](https://registry.npmjs.org/lucide-static/-/lucide-static-1.59.0.tgz). Geometry is unchanged; each SVG retains its license header. The complete ISC and Feather MIT notices are in `lucide/LICENSE`. See the [Lucide static guide](https://lucide.dev/guide/static).
- `fonts/ubuntu.css` and `fonts/ubuntu-*.woff2`: Ubuntu v21, normal weights 400, 500, and 700, including Latin, Greek, and Cyrillic subsets from [Google Fonts CSS](https://fonts.googleapis.com/css2?family=Ubuntu:wght@400;500;700&display=swap). The stylesheet only changes font URLs to local paths. Fonts load as needed and use `font-display: swap`. The [Ubuntu Font Licence 1.0](https://raw.githubusercontent.com/google/fonts/main/ufl/ubuntu/UFL.txt) is included as `fonts/UFL.txt`.

The icon names in `lucide/icons.json` are also used by the backend when assigning category icons. Keep existing names when updating the collection so saved category choices remain available.

`bookmarks/tiger-line.png` is the generated transparent line-art asset for the approved favorites design. CSS uses its alpha channel as a mask to recolor the same drawing in both themes; the mask remains outside the scrolling list. UI-only Lucide icons are excluded from random category/bookmark assignments.
