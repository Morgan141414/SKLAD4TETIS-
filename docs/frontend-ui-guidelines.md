# Frontend UI Guidelines

Scope: the current frontend is a vanilla HTML/CSS/JS operational warehouse UI. Keep changes local to `frontend/index.html`, `frontend/styles.css`, and `frontend/app.js`; do not introduce a bundler, global packages, or framework code unless the project explicitly changes direction.

## What to Reuse From Open Design

- Use `craft/state-coverage.md` as the default review checklist for every table, form, and panel: loading, empty, error, populated, and edge states must all be represented.
- Use `craft/accessibility-baseline.md` for semantic HTML, visible `:focus-visible`, labelled controls, keyboard reachability, live regions, and contrast checks.
- Use `craft/form-validation.md` for form behavior: validate after blur, preserve input on submit errors, disable only the submit path while pending, and show server errors near the affected fields.
- Borrow the `design-systems/dashboard` and `design-systems/application` structure, not the exact theme. The useful parts are token discipline, spacing scale, role colors, component inventory, and state coverage.
- Use the `frontend-design` skill as a thinking checklist for UI changes: real workflows first, dense operational layout, responsive checks, hover/focus/active/disabled states, and no decorative filler.

## Project Direction

- Favor a calm operational interface over marketing-style composition. This product is for repeated warehouse/accounting work, so density, scanability, predictable navigation, and clear tables matter more than large hero blocks or visual spectacle.
- Keep the current CSS-token approach. Add or refine `:root` variables for color roles, spacing, shadows, and radii instead of scattering raw values through component CSS.
- Keep panels and tables compact. Cards are acceptable for metrics, forms, repeated items, and bounded tools; avoid nested cards and decorative section wrappers.
- Treat green as the existing product accent, with blue only as a secondary information color. Preserve clear danger, warning, success, and muted states.
- Keep Russian UI labels literal and short. Operational users should not have to decode branding language.

## Checks Before UI Changes Land

- Keyboard: every action is reachable by Tab and has visible focus; buttons are real `<button>` elements and navigation links are real links when navigation is added.
- Forms: each input/select/textarea has a visible label, required fields use native constraints where possible, and server errors do not clear user-entered values.
- Tables: wide tables stay scrollable, columns keep readable alignment, long product names/lots do not break the layout, and empty states explain what to do next.
- Async states: section-level failures stay local; loading states do not replace the whole app chrome; retry actions are visible where recovery is possible.
- Responsive: check desktop, tablet-width, and narrow mobile. The sidebar, operator panel, topbar search/status/actions, forms, and table wrappers must not overlap.
- Accessibility: maintain `html lang="ru"`, useful live regions, sufficient color contrast, and non-color cues for warnings/errors.

## Extension Fit

- Suitable now: Open Design craft docs, `frontend-design` checklist, dashboard/application token patterns, and selected dashboard examples as reference material.
- Possibly useful later: Open Design MCP/desktop app for generating isolated prototypes before manually porting ideas into this vanilla frontend.
- Not suitable now: installing or running the full Open Design Node workspace. It requires Node `~24` and pnpm `10.33.x`, while this repository has no frontend package setup and should stay dependency-light for now.
- Not suitable now: Figma, image, deck, video, and prompt-template skills. They target artifact generation rather than this app's production UI.
- Not suitable now: copying brand-specific systems wholesale. Many are product-brand aesthetics; this project needs a restrained medical warehouse operations language.
