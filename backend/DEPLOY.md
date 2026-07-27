# Despliegue — DAO Ciudadana API

Guía para levantar el backend desde cero. Ruta gratuita: **MongoDB Atlas M0 + Render Free**.

> **Antes de empezar:** este backend todavía **no tiene autenticación** en ningún endpoint (hallazgo C-1 de [`docs/AUDIT.md`](../docs/AUDIT.md)). Cualquiera con la URL puede crear membresías, propuestas y votos. Despliégalo para desarrollo y demos, **no para usuarios reales**, hasta cerrar la Fase 1 del [`ROADMAP`](../docs/ROADMAP.md).

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
| Health check path | `/health` |

Luego define **`MONGO_URL`** en el dashboard. Es la única variable marcada `sync: false`, precisamente para que no viva en el repositorio.

**Verificar:**

```bash
curl https://<tu-servicio>.onrender.com/health
# → {"status":"healthy","version":"1.0.0","timestamp":"..."}
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
| `CORS_ORIGINS` | sí | Dominio del frontend, separado por comas. **No usar `*`** |
| `SECRET_KEY` | sí | Generada por Render (`generateValue: true`) |
| `DEBUG` | no | `false` en producción (`true` expone `/docs` y devuelve detalle de errores) |
| `CORS_ORIGIN_REGEX` | no | Regex para orígenes dinámicos (previews de Netlify). Ver abajo |
| `SBT_CONTRACT_ADDRESS` | no | `0x813fd379F715107b2451553d97f29408d8185f0e` |
| `EMERGENT_LLM_KEY` | no | Solo para el análisis de liveness real |

Detalle completo en [`.env.example`](./.env.example).

### Previews de Netlify y CORS

Cada deploy de Netlify recibe su propio subdominio (`<id>--tu-sitio.netlify.app`),
distinto en cada build. Si entras por esa URL en lugar de la de producción, el
navegador bloquea todas las peticiones: ese origen no está en `CORS_ORIGINS`.

En vez de ir añadiendo URLs a mano, define `CORS_ORIGIN_REGEX`:

```
^https://([a-z0-9-]+--)?TU-SITIO\.netlify\.app$
```

Acepta el dominio de producción y cualquier preview, y solo eso. El ancla `$`
final es lo que impide que `tu-sitio.netlify.app.dominio-atacante.com` pase el
filtro — no la quites.

**Defaults seguros:** si `CORS_ORIGINS` no está definida, la lista de orígenes permitidos queda vacía (deny-all) en lugar de `*`. Si `DEBUG` no está definida, vale `false`. Un despliegue sin configurar falla de forma visible, no de forma insegura.

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

Se retiraron dependencias que ningún módulo importaba: `openai`, `aiohttp`, `httpx`, `prometheus-client`, `python-jose`, `PyJWT`, `passlib`, `bcrypt`, `cryptography`, `email-validator` y `anyio`. Las de autenticación vuelven en la tarea 1.1 del roadmap, cuando exista código que efectivamente emita un JWT.

Dos que **no** se pueden quitar pese a no aparecer en ningún `import`:

- `python-multipart` — FastAPI lo exige para `UploadFile`/`File(...)` en `/api/auth/liveness`. Sin él, ese endpoint falla en runtime.
- `pymongo` — lo arrastra `motor`, pero queda fijado explícitamente porque la compatibilidad es estrecha (`motor 3.6` exige `>=4.9,<4.10`).

## Requisitos

Python **3.11**, fijado en `render.yaml` vía `PYTHON_VERSION` e igual en el CI.
