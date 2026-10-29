# 我的收藏 — design QA

final result: passed

## Scope and evidence

- Approved dark source: /Users/liumaodou/.codex/generated_images/01a14a80-f0fb-7ba1-a998-32825b11b59f/exec-8788b1ed-5613-4e43-8320-92686aa5e223.png
- Approved light source: /Users/liumaodou/.codex/generated_images/01a14a80-f0fb-7ba1-a998-32825b11b59f/exec-b0d29bbc-8b78-4da8-9adc-8da58718bcee.png
- Implementation: http://127.0.0.1:5231/#favorites
- Desktop captures: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/desktop-dark.png and desktop-light.png.
- Mobile captures: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/mobile-dark.png and mobile-light.png.
- Actual running app empty state: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/running-app-empty.png.
- Full-view paired source/implementation comparison: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/comparison.png.
- Native-density focused typography/toolbar/list comparison: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/comparison-focus.png.
- Functional results: /Users/liumaodou/.codex/visualizations/2026/10/17/01a14a80-f0fb-7ba1-a998-32825b11b59f/favorites-implementation/functional-results.json.

## Normalization and state

Sources and desktop implementation are 1536 × 1024 pixels. Implementation uses a 1536 × 1024 CSS viewport at deviceScaleFactor 1. Full-view comparison renders both at half size together; the focused comparison renders source/implementation crops at native density. No browser chrome or device bezel is included. Both show 开发资源, name ascending, six links, and the first row hovered. The same source names/dates and representative Lucide icons were seeded only into the isolated QA database. The actual user database remains empty; sample records were not copied into it.

Mobile was checked in touch mode at 390 × 844 and 320 × 568, plus a 667 × 375 landscape viewport. The folder pane becomes a drawer. Browser plugin/skill was not available; bundled Playwright with installed Chrome was used. No additional browser dependencies were installed.

## Findings and comparison history

1. [P2, fixed] Initial mobile capture had extra document height because the empty tool-category message and desktop-only navigation margin increased the app header beyond its expected mobile height. Hide that message in the favorites view, reset the system-entry mobile margin, and remove the forced minimum favorites height. Recaptured mobile output fits the viewport, with no repeated sticky header or horizontal overflow.
2. [P2, fixed] Initial favorite names used 15px medium type, which was heavier and smaller than the selected list treatment. Use 16px regular Ubuntu/system-fallback type on desktop, retain 14px on narrow screens, and enlarge the folder heading to 24px. The final focused comparison shows the corrected hierarchy.
3. [P2, fixed] The added-date legend initially used a separate width from the scrolling list, leaving its alignment dependent on scrollbar gutters. Move the legend into the same scroll content and align it to the same grid columns. Dates and their heading now align.
4. [P2, fixed] Muted light-theme dates needed clearer small-text contrast. Adjust the date token to #697464; the date remains secondary to bookmark names. Dark dates use #a0aa9b.

Final comparison: no actionable P0/P1/P2 findings remain.

## Required fidelity surfaces

- Typography: locally hosted Ubuntu with Yuanti SC / Microsoft YaHei fallbacks. Names are regular-weight, clipped to one line with overflow-only tooltips; dates are smaller, tabular, and visually secondary. Headings, labels, search and sort remain readable.
- Spacing/layout: retains the existing app shell and adds a dedicated folder pane plus lightweight 56px bookmark rows. Toolbar wraps at intermediate widths. Folder drawer, sorting, search, date column and action buttons fit 320–1536px widths.
- Colors/tokens: existing Morandi light/dark tokens are reused. Both themes recolor the same tiger alpha mask. Focus/hover/selected/error states remain distinct.
- Image quality: the transparent 1254 × 1254 generated tiger PNG uses fine contour lines with empty interiors. It is an alpha mask rather than a screenshot or a fabricated SVG. Its position is outside the scrolling row container; browser tests confirm the stage/mask remain stationary as row coordinates change by 250px.
- Copy/content: 我的收藏, system folders, create/edit/move/delete, sorting, search, dates and confirmation messages are implemented. Folder deletion explicitly retains links in 未分类. Names and URLs are escaped/validated. Empty/loading/error states use real data.

## Expected integration differences

- Existing 220px app navigation and the requested font stack are retained rather than replacing the entire app with the raster mock's slightly different proportions.
- Real folders use locale-aware name ordering; mock folders were manually arranged.
- Bookmark icons are randomly assigned from bundled Lucide icons, so individual symbols/colors need not match a static mock.
- Row density is intentionally compact. Live dates are generated on creation and formatted in the browser's timezone; arbitrary mock dates are not hardcoded in production.
- The independently generated line-art asset follows the approved pose/style but is not a pixel trace of the mock.

## Functional verification

- 29 backend regression tests passed, including existing tools, independent favorites, startup persistence, stable icon/date, URL/read-only-field validation, and retaining links on folder deletion.
- Browser flow passed: empty state → create folder → create links → name/numeric sorting → reload persistence → name/URL search → edit/move → rename/remove folder → delete link.
- Failed saves retain entered values and allow retry; failed loads have a working retry action.
- Stored markup remains inert; menus support arrow keys and Escape. Existing tool creation/editing still work.
- Light/dark responsive checks at 320, 390, 540, 768, 1024, 1536px passed. No page runtime errors; console errors were limited to deliberately simulated 409/503 responses.
- Real local app was restarted after a SQLite backup, then checked read-only via HTTP and browser. Its favorites snapshot and static assets respond successfully.
- JavaScript syntax and git diff whitespace checks passed.

## Remaining coverage

Browser interaction coverage is Chrome/Chromium. Safari and Firefox have not been separately exercised. No deployment or GitHub push was performed.

## Implementation checklist

- [x] Folder and bookmark persistence; independent of existing directory records.
- [x] Built-in navigation, CRUD dialogs, menus, filtering, sorting, date display.
- [x] Random persisted Lucide icons and fixed, theme-aware tiger background.
- [x] Desktop/mobile, empty/error/retry, accessibility and existing-flow regression checks.
- [x] Paired final reference comparison and actual local preview.
