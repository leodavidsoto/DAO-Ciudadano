# Despliegue — DAO Ciudadana API

Guía para levantar el backend desde cero. Ruta gratuita: **MongoDB Atlas M0 + Render Free**.

> **Antes de empezar:** el backend ya usa sesión SIWE para varias acciones,
> pero el alta de identidad aún no emite un permiso de minteo ligado a la
> wallet y no existe un contrato compatible desplegado. El blueprint se
> declara como `APP_ENV=demo` + `MINT_MODE=demo`: es un piloto, **no un entorno
> apto para usuarios reales**. `APP_ENV=production` falla cerrado a propósito.

> **Datos existentes:** el código cifra altas nuevas, pero no migra por sí solo
> documentos legacy de `users` ni los convierte en identidad verificada. Antes
> de reutilizar el Atlas actual en producción: snapshot, inventario de campos y
> duplicados, migración ensayada, validación y plan de rollback. Los índices
> únicos/readiness fallan cerrado si los datos viejos son incompatibles.

---

## Paso 1 — Base de datos (MongoDB Atlas M0)

1. Crear cuenta en [mongodb.com/cloud/atlas](https://www.mongodb.com/cloud/atlas) y desplegar un clúster **M0** (gratuito).
2. **Database Access** → crear un usuario con permisos de lectura/escritura.
3. **Network Access** → permitir `0.0.0.0/0`. Render no publica IPs fijas en el plan gratuito, así que no hay forma de restringir por origen.
4. Copiar la cadena de conexión (`mongodb+srv://usuario:clave@...`). Ese es el valor de `MONGO_URL`.

**Nunca subas esa cadena al repositorio.** Va solo en el dashboard de Render.

> `0.0.0.0/0` deja el clúster alcanzable desde cualquier IP; la única barrera es la contraseña. Usa una larga y generada al azar, y distinta de cualquier otra que uses. Cuando el proyecto pase a un plan con IPs fijas, restringe el rango.

---

## Paso 2 — API (Render Free)

El repositorio trae `backend/render.yaml` con `plan: free`, así que:

**Opción A — Blueprint (recomendada)**
Render → **New → Blueprint** → conectar el repositorio y apuntar a `backend/render.yaml`. Toma toda la configuración de ahí.

**Opción B — Web Service manual**

| Campo | Valor |
|---|---|
| Root directory | `backend` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Instance type | Free |
| Health check path | `/health/ready` |

Un servicio manual **no hereda** ninguna variable del blueprint. Define todas
las filas obligatorias de la tabla inferior. Para el piloto actual usa, como
mínimo: `APP_ENV=demo`, `MINT_MODE=demo`, `MEMBERSHIP_SOURCE=mongo`,
`SIGNED_BALLOTS_REQUIRED=false`, `DEBUG=false`, `DB_NAME`, `MONGO_URL`,
`CORS_ORIGINS`, `SIWE_DOMAIN`, `SIWE_URI`, `SIWE_CHAIN_ID`,
`IDENTITY_PEPPER`, `PII_ENCRYPTION_KEY` y un `SECRET_KEY` nuevo.

Genera los secretos localmente y copia solo el resultado al dashboard:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"  # SECRET_KEY / pepper (distintos)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Verificar:**

```bash
curl https://<tu-servicio>.onrender.com/health/ready
# El piloto debe indicar environment=demo, minting.mode=demo y
# production_ready=false. Un entorno production incompleto devuelve HTTP 503.
```

> **Arranque en frío:** en el plan gratuito Render suspende el servicio tras ~15 min sin tráfico. La primera petición después de eso tarda 30–60 s. No es un fallo del despliegue.

---

## Paso 3 — Conectar el frontend

La URL del backend **cambia al recrear el servicio**. Hay que actualizarla en dos lugares, y ambos son obligatorios:

1. `frontend/netlify.toml` → `REACT_APP_BACKEND_URL`
2. La variable `CORS_ORIGINS` del backend debe contener el **dominio exacto** del frontend (con `https://`, sin barra final)

Sin el paso 2 el navegador bloquea todas las peticiones y la app aparece rota sin error visible en la UI — el fallo solo se ve en la consola.

Después, **redesplegar el frontend** (Netlify no relee `netlify.toml` sin un nuevo build).

---

## Variables de entorno

| Variable | Obligatoria | Valor |
|---|---|---|
| `MONGO_URL` | sí | Cadena de conexión de Atlas. **Solo en el dashboard.** |
| `DB_NAME` | sí | `dao_ciudadana` |
| `APP_ENV` | sí | `demo` para el piloto; `production` solo cuando todos los bloqueos estén cerrados |
| `MINT_MODE` | sí | `demo`, `disabled` u `onchain`; nunca hay fallback implícito |
| `CORS_ORIGINS` | sí | Dominio del frontend, separado por comas. **No usar `*`** |
| `SECRET_KEY` | sí | Generada por Render (`generateValue: true`) |
| `IDENTITY_PEPPER` | sí | Secreto HMAC; solo en el dashboard/gestor de secretos |
| `PII_ENCRYPTION_KEY` | sí | Clave Fernet; solo en el dashboard/gestor de secretos |
| `DEBUG` | no | `false` en producción (`true` expone `/docs` y devuelve detalle de errores) |
| `CORS_ORIGIN_REGEX` | no | Solo desarrollo/demo; debe quedar vacío en producción |
| `SIWE_DOMAIN` | sí | Dominio público exacto mostrado en la firma, sin esquema (ej. `estamosdao.cl`) |
| `SIWE_URI` | sí | URI HTTPS del frontend; su host debe coincidir con `SIWE_DOMAIN` |
| `SIWE_CHAIN_ID` | sí | `11155111` mientras el entorno use Sepolia |
| `RATE_LIMIT_REQUESTS` | no | Presupuesto global por IP/minuto; default `100` |
| `RATE_LIMIT_SENSITIVE_REQUESTS` | no | Presupuesto agregado por IP/minuto para auth, mint y votos; default `30` |
| `RATE_LIMIT_WINDOW_SECONDS` | no | Ventana de ambos presupuestos; default `60` segundos |
| `TRUSTED_PROXY_IPS` | no | IP/CIDR, separados por comas, de proxies cuya cabecera `X-Forwarded-For` se haya verificado; vacío usa el peer TCP |
| `MEMBERSHIP_SOURCE` | sí | `mongo` en el piloto; `onchain` aún falla cerrado porque no está implementado |
| `SIGNED_BALLOTS_REQUIRED` | sí | `false` en demo; producción exige `true` |
| `SBT_CONTRACT_ADDRESS` | solo on-chain | Nueva dirección AccessControl/bytes32; **no** reutilizar `0x813f…` |
| `SEPOLIA_RPC_URL` | solo on-chain | RPC de la red del contrato |
| `MINTER_PRIVATE_KEY` | solo on-chain | Secreto con `MINTER_ROLE`; preferir KMS/relayer antes de producción |
| `EMERGENT_LLM_KEY` | no | Solo demo técnico; un LLM generalista no es liveness de producción |

`SIWE_DOMAIN`, `SIWE_URI` y `CORS_ORIGINS` deben identificar el mismo host
canónico. Configura `www` y el subdominio técnico de Netlify para redirigir a
ese host antes de cargar la aplicación; no los habilites como orígenes SIWE
alternativos sin implementar desafíos ligados al `Origin` validado.

`TRUSTED_PROXY_IPS` no contiene IPs de usuarios: autoriza qué proxies pueden
aportar `X-Forwarded-For`. Déjala vacía hasta confirmar los peers/rangos mediante
configuración o documentación vigente del proveedor. No asumas rangos de Render
ni uses `*`; un rango demasiado amplio vuelve falsificable la identidad usada
por el rate limiter. Con la variable vacía el comportamiento es seguro, aunque
una plataforma que no normalice `request.client` puede agrupar tráfico detrás
del mismo proxy y requerir configuración operativa posterior.

Detalle completo en [`.env.example`](./.env.example).

### Previews de Netlify y CORS (solo demo/desarrollo)

Cada deploy de Netlify recibe su propio subdominio (`<id>--tu-sitio.netlify.app`),
distinto en cada build. Si entras por esa URL en lugar de la de producción, el
navegador bloquea todas las peticiones: ese origen no está en `CORS_ORIGINS`.

En un backend separado con `APP_ENV=demo`, puedes definir
`CORS_ORIGIN_REGEX`:

```
^https://([a-z0-9-]+--)?TU-SITIO\.netlify\.app$
```

El ancla `$` impide que `tu-sitio.netlify.app.dominio-atacante.com` pase el
filtro. No uses este patrón en el backend de producción: allí readiness exige
regex vacío, un origen canónico exacto y redirecciones de aliases antes de que
la app cargue.

**Defaults seguros:** si `CORS_ORIGINS` no está definida, la lista queda vacía
(deny-all); `DEBUG` vale `false`; `APP_ENV` vale `production`; y `MINT_MODE`
vale `disabled`. Por eso un despliegue incompleto devuelve 503 en readiness y
no crea membresías off-chain silenciosamente.

---

## Docker (local o cualquier otro host)

```bash
docker build -t dao-api ./backend

docker run -p 8000:8000 \
  -e MONGO_URL='mongodb+srv://...' \
  -e CORS_ORIGINS='http://localhost:3000' \
  dao-api
```

El contenedor respeta `$PORT`, así que la misma imagen sirve para Cloud Run, Koyeb o Fly.io sin cambios.

---

## Desarrollo local

```bash
cd backend
cp .env.example .env          # completar MONGO_URL
pip install -r requirements-dev.txt
uvicorn main:app --reload --port 8000
```

Con `DEBUG=true` la documentación interactiva queda en `http://localhost:8000/docs`.

---

## Dependencias

- **`requirements.txt`** — solo producción. Se mantuvo mínimo a propósito: en 512 MB de RAM y con arranque en frío, cada wheel innecesaria cuesta tiempo de build y latencia.
- **`requirements-dev.txt`** — incluye lo anterior más `pytest`, `mongomock` y linters. Es lo que instala el CI.

La imagen de producción incluye `cryptography` (PII), `PyJWT`/`eth-account`
(SIWE y EIP-712) y `web3` (camino on-chain). `httpx` permanece solo en
`requirements-dev.txt`. Las demás dependencias retiradas están enumeradas en
`requirements.txt`.

Dos que **no** se pueden quitar pese a no aparecer en ningún `import`:

- `python-multipart` — FastAPI lo exige para `UploadFile`/`File(...)` en `/api/auth/liveness`. Sin él, ese endpoint falla en runtime.
- `pymongo` — lo arrastra `motor`, pero queda fijado explícitamente porque la compatibilidad es estrecha (`motor 3.6` exige `>=4.9,<4.10`).

## Requisitos

Python **3.11**, fijado en `render.yaml` vía `PYTHON_VERSION` e igual en el CI.


---

## Checklist de producción tras ADR-001 (02-08-2026)

`/health/ready` es la fuente de verdad: enumera lo que falta y, en `features`,
**qué puede hacer realmente** el despliegue. Un `ready: true` con
`features.identity_issuance.available: false` significa que el servicio está
sano pero nadie puede darse de alta.

### Variables nuevas y qué se rompe sin cada una

| Variable | Si falta |
|---|---|
| `IDENTITY_ISSUER_PRIVATE_KEY` | No se emite ninguna credencial ZK. **Bloquea producción.** Debe ser una llave Ethereum válida y distinta de `MINTER_PRIVATE_KEY` |
| `IDENTITY_PROVIDER` | No se pueden emitir grants civiles: el alta de ciudadanos queda bloqueada. **Bloquea producción** |
| `REDIS_URL` | Rate limiter y antifraude cuentan por proceso: con N instancias el límite efectivo es N veces el configurado. **Bloquea producción** |
| `SBT_CONTRACT_ADDRESS` | No se puede leer `membershipScope()` ni aprobar raíces. **Bloquea producción** |
| `BUNDLER_RPC_URL` | Sin patrocinio de gas; el minteo cae al relayer EOA, que sí funciona |
| `MACI_COORDINATOR_ADDRESS` | El registro de llaves MACI sigue activo, pero no se puede anunciar poll |

### Lo que NO debe definirse

- **`SAFE_OWNER_PRIVATE_KEY`** — el backend no es owner ni custodio de las
  Safes. Configurarla se reporta como error de configuración, no como opción.

### Orden de encendido sugerido

1. Desplegar el contrato SBT y anotar su dirección → `SBT_CONTRACT_ADDRESS`.
2. Conceder `ROOT_MANAGER_ROLE` a la llave del relayer: aprueba raíces de
   identidad, que es un permiso distinto del de mintear.
3. Provisionar Redis → `REDIS_URL`.
4. Generar la llave del emisor → `IDENTITY_ISSUER_PRIVATE_KEY`.
5. Integrar el proveedor civil → `IDENTITY_PROVIDER`.
6. Solo entonces `APP_ENV=production` y `SIGNED_BALLOTS_REQUIRED=true`.
7. ERC-4337 al final, con `ERC4337_ENABLED=true`: comprobar en
   `/health/ready` que `erc4337.bundler.reachable` es true y que el
   `chain_id` coincide antes de dar por buena la integración.

### Lo que sigue sin poder verificarse desde aquí

- Ninguna UserOperation se ha enviado nunca: hace falta una Safe desplegada y
  saldo en el paymaster.
- Los circuitos ZK no tienen ceremonia multiparte; quien generó los `zkey`
  actuales puede fabricar pruebas falsas.
- La llave filtrada de P-18 sigue sin rotar. Es lo único P0 del proyecto.
