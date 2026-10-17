# 毛豆百脑汇

A small, self-hosted directory for bookmarks and tools. Browse by category, switch between light and dark themes, and use edit mode to manage categories, links, descriptions, logos, and ordering.

## Run locally

Python 3.9 or newer is required. There is no Node.js build step.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python api.py
```

Open [http://127.0.0.1:5231](http://127.0.0.1:5231). The same Flask application serves the page, JavaScript, API, and uploads. A fresh database starts empty; enable edit mode to add the first category.

## Structure

- `index.html`: page structure and accessible controls.
- `styles.css`: responsive layouts and shared Morandi color tokens for light/dark themes.
- `theme.js`: applies the saved theme before the stylesheet loads; otherwise follows the system preference, including live changes. Manual choices persist and sync between tabs.
- `app.js`: API requests, grouped rendering, editing, ordering, and uploads. Stored text is escaped, and stored SVG markup is rendered in an image context.
- `api.py`: Flask application, validation, SQLite initialization/migration, and file serving. `create_app(config)` supports isolated test instances; `api:app` is the WSGI entry point.
- `tests/test_api.py`: migration, CRUD, ordering, validation, rollback, and upload regression tests.
- `all_nav.db` and `uploads/`: runtime data, excluded from Git. Cloning this repository does not copy existing bookmarks or logos.

## Data and ordering

The `ai_nav_flat` table retains the original fields: `id`, `category`, `name`, `logo`, `description`, `url`, `sort_order`, and `created_at`. A row with `name = NULL` represents an empty category.

`category_sort_order` is migrated automatically at startup. Migration preserves existing IDs, content, URLs, tool ordering, and the category order displayed by the old frontend. Subsequent startups leave the migrated ordering intact. Category names remain the grouping key; renaming/deleting a category affects all of its rows.

Category order and tool order are independent. Reordering is committed in one SQLite transaction and rejects missing, duplicate, or foreign entries. A stale list receives HTTP 409 and should be reloaded. Concurrent complete reorder requests use the last successfully committed order.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `5231` | Port for `python api.py`; binds to `127.0.0.1`. |
| `ALL_NAV_DB` | `all_nav.db` beside `api.py` | SQLite database path; parent directory must exist. |
| `ALL_NAV_UPLOAD_DIR` | `uploads/` beside `api.py` | Directory for uploaded logos; created on startup. |

Uploads support PNG, JPEG, GIF, WebP, ICO, and SVG. The complete upload request is limited to 5 MiB; raster images are limited to 20 megapixels and verified against their extensions. SVGs are displayed as images; responses for uploaded files also carry a restrictive sandbox policy. Local upload URLs stay relative to the application origin.

## API

| Method and path | Behavior |
| --- | --- |
| `GET /api/ai_nav_flat` | Return rows in category and tool order. |
| `POST /api/ai_nav_flat` | Insert an object or a batch of up to 500 objects. `category` is required; `name: null` creates a category. |
| `PATCH /api/ai_nav_flat?eq_id=123` | Edit a tool. URLs must use HTTP or HTTPS. Changing category appends the tool to an existing destination category. |
| `PATCH /api/ai_nav_flat?eq_category=Name` | Rename a category with `{"category":"New name"}`. Existing destination names are rejected. |
| `DELETE /api/ai_nav_flat?eq_id=123` | Delete a tool while retaining its category. |
| `DELETE /api/ai_nav_flat?eq_category=Name` | Delete the category and all its tools. |
| `POST /api/reorder` | Categories: `{"kind":"categories","order":["B","A"]}`. Tools: `{"kind":"tools","category":"A","order":[3,1,2]}`. Include the entire current category/tool list. |
| `POST /api/upload` | Multipart `file`; returns `{"url":"/uploads/<generated-name>"}`. |

Errors return a JSON `error` string. Mutation filters support `eq_id` and `eq_category`. IDs, timestamps, and category ordering cannot be edited through generic PATCH requests. The old category-wide `sort_order` update must be replaced with `/api/reorder`; deploy the frontend and backend together.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check app.js && node --check theme.js  # optional, if Node.js is installed
```

The tests use temporary databases and upload directories. They cover migration without losing legacy fields, reorder persistence, category moves, atomic rollback, malformed requests, unsafe link schemes, static file boundaries, and upload validation.

## Deployment and backup

The built-in server is for local development. For a hosted instance, serve `api:app` with a production WSGI server and preserve the original Host header in the reverse proxy. Proxy all paths to the application to retain its upload security headers. If static files are served separately, include `app.js`, `theme.js`, and `styles.css`, and apply the same sandbox/content-type headers to uploads.

This application retains the original shared editing model: it has **no built-in authentication**. Keep it local or behind an authenticated reverse proxy. The edit button changes the interface; it is not an access-control boundary.

Before upgrading an existing deployment, stop its writers and back up `all_nav.db` together with `uploads/`. For a live SQLite database, use SQLite's backup API instead of copying only the main file while WAL writes are active. Test the upgrade on a backup first. The added ordering column is not removed automatically when rolling back application code.

Theme behavior uses native [color-scheme](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/color-scheme) and system preferences. System fonts avoid third-party font requests. Mobile editing switches to a single column below 540px with larger action buttons.

References: [Flask uploads and request limits](https://flask.palletsprojects.com/en/stable/patterns/fileuploads/), [SVG image restrictions](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image).
