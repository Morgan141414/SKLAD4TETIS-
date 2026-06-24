# Tetis SSO ACL

SKLAD is embedded into Tetis through `https://tetis1.kz/sklad/`.
Tetis issues short-lived SKLAD JWTs through `POST /api/v1/sklad/token`.

By default, the token endpoint keeps the transitional behavior: selected Tetis
management roles receive `warehouse_manager` with global warehouse access.
This keeps the current deployment working until real warehouse ownership is
configured.

SKLAD stores the company-to-warehouse mapping on warehouse records:

- `warehouses.tetis_org_id`: active Tetis company/organization id.
- `warehouses.external_tetis_id`: optional warehouse id from Tetis or another
  external catalog.

When Tetis issues a scoped SKLAD token, it must resolve the active `org_id`
through this mapping and put local SKLAD warehouse ids into JWT `warehouse_ids`.
Do not put Tetis company ids into `warehouse_ids`; those ids are not SKLAD
warehouses and will be rejected by scoped warehouse endpoints.

Tetis can resolve the mapping through the service lookup endpoint:

```http
GET /api/v1/tetis/orgs/{tetis_org_id}/warehouse-ids
Authorization: Bearer <SKLAD service token with warehouse_manager role>
```

Response:

```json
{
  "tetis_org_id": "71114554532",
  "warehouse_ids": [1, 2]
}
```

The endpoint requires `admin:users`; use it from the Tetis token service, not
from an ordinary browser session.

For production least-privilege access, set `SKLAD_ACCESS_JSON` on the Tetis
backend container only as a temporary override or fallback. When this variable
is present, access becomes explicit: unmapped users receive `403`.

Example:

```json
{
  "roles": {
    "founder": { "role": "warehouse_manager" },
    "ceo": { "role": "warehouse_manager" },
    "hr": { "role": "head_nurse", "warehouse_ids": [1, 2] },
    "doctor": { "role": "doctor", "warehouse_ids": [2] }
  },
  "users": {
    "00000000-0000-0000-0000-000000000000": {
      "role": "nurse",
      "warehouse_ids": [1]
    }
  },
  "platform_roles": {
    "superadmin": { "role": "warehouse_manager" }
  }
}
```

Supported SKLAD roles:

- `warehouse_manager`: all permissions and all warehouses. Use only for an
  explicit allowlist.
- `head_nurse`: stock read/receive/writeoff/transfer/reserve, documents create,
  inventory manage, notifications read. Requires `warehouse_ids`.
- `nurse`: stock read/writeoff and notifications read. Requires `warehouse_ids`.
- `doctor`: stock read/reserve. Requires `warehouse_ids`.
- `other`: stock writeoff only. Requires `warehouse_ids`.

Precedence:

1. `orgs.<org_id>.users.<user_id>`
2. `users.<user_id>`
3. `orgs.<org_id>.roles.<tetis_role>`
4. `roles.<tetis_role>`
5. `platform_roles.<platform_role>`
6. `orgs.<org_id>.default`
7. `default`

Operational rules:

- Keep `SKLAD_DEV_AUTH_ENABLED=false` outside local/demo.
- Keep `SKLAD_JWT_ISSUER=tetis` and `SKLAD_JWT_AUDIENCE=sklad`.
- Do not put tokens into URLs; SKLAD frontend stores the returned token only in
  the hidden auth field for API calls.
- Scoped roles must have integer `warehouse_ids`; empty warehouse scope is
  rejected by the Tetis token endpoint when ACL config is enabled.
- Frontend reconciliation is only a usability fallback. Backend authorization
  must rely on the JWT role and local SKLAD `warehouse_ids`.

Troubleshooting:

- If a request fails with `warehouses#<number> not found`, first check that
  `<number>` is not a Tetis company id. The token endpoint must return local
  SKLAD warehouse ids in `warehouse_ids`.
- If the active Tetis company has no stock data, check that at least one SKLAD
  warehouse has `tetis_org_id` equal to the active Tetis `org_id`.
- If optional dashboard blocks return `Permission denied`, keep those widgets
  behind frontend `loadOptional` fallbacks unless the role truly needs that
  permission. Core warehouse operations must still fail loudly when access is
  missing.
