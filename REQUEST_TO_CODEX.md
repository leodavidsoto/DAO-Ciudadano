# Backend listo para la tarea 1.13 (sesión fuera de `localStorage`)

**De:** Claude (backend + contratos) · **Para:** Codex (frontend)
**Fecha:** 02-08-2026 · **Rama:** `codex/produccion-ci`

El backend ya emite y acepta la sesión por cookie. Nada de lo que hay hoy en el
frontend deja de funcionar: `POST /api/wallet/verify` sigue devolviendo `token`
en el body por defecto. La migración es tuya y puede hacerse en un solo paso.

---

## 1. Contrato de la API

### `POST /api/wallet/verify`

Request (el campo nuevo es opcional):

```json
{
  "address": "0x…",
  "nonce": "…",
  "signature": "0x…",
  "session_transport": "cookie"
}
```

- `session_transport: "token"` (por defecto) → el body incluye `token`.
  Es lo que usa la app móvil; **no lo quites del backend**.
- `session_transport: "cookie"` → `token` viene `null`. La sesión existe solo
  en la cookie `HttpOnly`, así que no queda ninguna copia que un XSS pueda leer.
  **Usa este valor en la web.**

Response:

```json
{
  "address": "0x… (checksum)",
  "expires_in": 3600,
  "csrf_token": "hex de 64 caracteres",
  "token": null
}
```

Cookies que fija la respuesta:

| Cookie | Flags | Para qué |
|---|---|---|
| `dao_session` | `HttpOnly`, `Secure` (prod), `SameSite=None` (prod) / `Lax` (local), `Path=/` | El JWT. JavaScript no puede leerla. |
| `dao_csrf` | **sin** `HttpOnly`, mismos demás flags | La mitad legible del doble envío CSRF. |

### `GET /api/wallet/session`

Devuelve `{ "address": "0x… (minúsculas)", "csrf_token": "…" }`, o **401** si no
hay sesión válida. Es la forma de restaurar el estado al cargar la página: con
la cookie en `HttpOnly` el frontend ya no puede mirar el JWT para saber quién
es. Llámalo al montar la app en vez de leer `localStorage`.

### `POST /api/wallet/logout`

Borra ambas cookies. No requiere autenticación ni CSRF (cerrar sesión con una
cookie ya corrupta tiene que funcionar).

**Sé honesto en la UI:** esto cierra la sesión del navegador, **no revoca el
JWT**, que sigue siendo válido hasta que expire (`expires_in`). La revocación
real necesita almacenamiento compartido y todavía no existe.

---

## 2. Lo que tienes que hacer en el cliente

1. **`fetch`/axios con credenciales.** `credentials: 'include'` (o
   `withCredentials: true`) en **todas** las llamadas a la API. Sin eso el
   navegador no manda la cookie y todo responde 401.
2. **Cabecera CSRF en métodos con efectos.** En `POST`/`PUT`/`DELETE`/`PATCH`
   añade `X-CSRF-Token` con el valor de la cookie `dao_csrf` (o el
   `csrf_token` que devolvieron `/verify` o `/session`). Sin ella la respuesta
   es **403** con un detalle que lo dice explícitamente.
   `GET`/`HEAD`/`OPTIONS` no la necesitan.
3. **Deja de guardar el JWT.** Ni `localStorage` ni `sessionStorage` ni memoria
   global: pide `session_transport: "cookie"` y no vas a tener nada que guardar.
   Lo único que conviene mantener en memoria es la `address` que responde
   `/wallet/session`.
4. **401 → limpia el estado y vuelve a SIWE.** Una cookie expirada no se
   distingue de "nunca inició sesión".

El header `Authorization: Bearer` sigue aceptándose y **tiene prioridad** sobre
la cookie. Si mandas los dos, gana el header — útil para migrar por pantallas
sin romper nada, pero no dejes ese estado mixto en el commit final.

---

## 3. Configuración que hay que coordinar

- `CORS_ORIGINS` debe listar tu origen exacto. Con `*` el backend **desactiva**
  las credenciales a propósito (Starlette reflejaría cualquier origen y le
  entregaría la cookie de sesión); en producción `*` ya estaba prohibido.
- En producción las cookies salen con `SameSite=None; Secure` porque Netlify y
  Render son sitios distintos. En local, `SameSite=Lax` sobre `http://localhost`.
- Variables nuevas documentadas en `backend/.env.example`: `SESSION_COOKIE_NAME`,
  `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_DOMAIN`,
  `CSRF_COOKIE_NAME`. Vacías = valores derivados del entorno, que es lo correcto
  en casi todos los casos.

**Pendiente tuyo también:** `e2e/tests/support/e2e-fixture.js:348` simula
`/api/wallet/verify` devolviendo solo `{token, address}`. Cuando migres, ese
doble tiene que fijar las cookies y devolver `csrf_token`, o el E2E validará un
flujo que ya no existe.

---

## 4. Contratos desplegados en Sepolia (pendiente de fijar en el frontend)

| Contrato | Dirección |
|---|---|
| `MACICoordinator` | `0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6` |
| `TallyVerifier` | `0x3817516c4fa354c9F24f6deCE0eA636048c54D87` |

`REACT_APP_MACI_TALLY_VERIFIER_ADDRESS` debería fijar el `TallyVerifier` y
contrastarlo contra la cadena, igual que ya se hace con el coordinador.

Recordatorio de honestidad, no de configuración: la ceremonia del `zkey` fue de
una sola contribución y local, así que **no es apta para una elección
vinculante**. `/api/maci/status` sigue declarando `private_voting: false` y la
UI no debe prometer voto privado. Detalle en `docs/AUDIT.md`.

---

## 5. Del lado del backend, en esta misma entrega

Fase 3.1 cerrada: `MEMBERSHIP_SOURCE=onchain` ya consulta
`hasMembership(address)` en el SBT con caché corta. **No cambies la variable en
el despliegue**: el contrato todavía no tiene membresías (`totalSupply()` = 0) y
todo el mundo recibiría 403. Lo que sí te afecta: cuando esté activo, un fallo
del RPC responde **503**, no 403. Trátalos distinto en la UI — 403 es "no eres
miembro", 503 es "no pudimos comprobarlo ahora".
