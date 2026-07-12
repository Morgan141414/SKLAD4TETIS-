# marqet.kz public frontend

This Vite/React app is the public storefront served on `marqet.kz`.

## Commands

```bash
npm ci
npm run build
```

The production build is emitted to `dist/`. On the current server, nginx serves
the public storefront from `/opt/marqet/dist` and proxies `/api/` to the Sklad
backend.

Keep generated folders (`node_modules/`, `dist/`) out of git.
