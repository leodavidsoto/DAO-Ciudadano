# 🏛️ DAO Ciudadana

> Piloto abierto de membresía y gobernanza ciudadana con controles fail-closed

![Version](https://img.shields.io/badge/version-1.0.0-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![React](https://img.shields.io/badge/React-19-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.140-teal)

> ⚠️ **Estado actual (agosto 2026): piloto técnico, no servicio de identidad.**
> ClaveÚnica, NFC y liveness siguen siendo demostraciones y están bloqueados con
> `APP_ENV=production`. Minteo y acciones mutantes de gobernanza exigen SIWE, pero la
> creación de membresías de producción permanece cerrada hasta implementar un
> permiso de verificación de un solo uso y desplegar un contrato compatible. El
> contrato histórico de Sepolia no es compatible con el código actual y tiene
> `totalSupply() == 0`. Revisa el estado y el plan en [`docs/`](./docs):
> [AUDIT](./docs/AUDIT.md) · [ROADMAP](./docs/ROADMAP.md) · [HANDOFF](./docs/HANDOFF.md) · [SECURITY RUNBOOK](./docs/SECURITY_RUNBOOK.md).

## 🎯 Descripción

DAO Ciudadana explora una plataforma de participación y membresía digital. Hoy
permite probar la experiencia y la gobernanza autenticada por wallet, pero **no
verifica identidad civil ni emite una credencial on-chain en producción**.

- **Cuenta piloto**: RUT/email cifrados; son datos declarados, no acreditación.
- **ClaveÚnica, NFC y liveness**: recorridos demostrativos, bloqueados en producción.
- **Wallet**: challenge/verify SIWE real para probar control de la dirección.
- **Membresía**: demo off-chain explícito; producción falla cerrado.

## 🚀 Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env  # Configurar variables
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm ci
npm start
```

Abrir http://localhost:3000

## 📁 Arquitectura

```
DAO-Ciudadano/
├── backend/
│   ├── app/
│   │   ├── core/           # Config, security, database
│   │   ├── models/         # Pydantic schemas
│   │   ├── routers/        # API endpoints
│   │   └── services/       # Business logic
│   ├── main.py             # Entry point
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── onboarding/ # Step components
│   │   │   └── ui/         # Radix UI components
│   │   ├── context/        # React Context (state)
│   │   ├── lib/            # API service
│   │   ├── pages/          # Page components
│   │   └── App.js          # Main entry
│   └── package.json
│
└── contracts/              # Contrato SBT actual + tests Hardhat
```

## 🔌 API Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/auth/clave-unica` | POST | Demo de ClaveÚnica (bloqueado en producción) |
| `/api/auth/nfc` | POST | Demo NFC (no verifica identidad; bloqueado en producción) |
| `/api/auth/liveness` | POST | Demo de liveness (bloqueado en producción) |
| `/api/wallet/challenge` | POST | Crear desafío SIWE de un solo uso |
| `/api/wallet/verify` | POST | Verificar firma SIWE y emitir sesión |
| `/api/membership/mint` | POST | Crear membresía según `MINT_MODE` |
| `/api/dashboard/stats` | GET | Estadísticas DAO |
| `/api/governance/ballot-schema` | GET | Esquema EIP-712 para firmar propuestas |
| `/api/governance/proposals/{id}/ballots` | GET | Evidencia pública para reverificación |
| `/health/live` | GET | Liveness del proceso |
| `/health/ready` | GET | Readiness fail-closed de la instancia |

## 🛠️ Stack Tecnológico

### Backend
- **FastAPI** - Framework async de alto rendimiento
- **MongoDB** (Motor) - Base de datos NoSQL
- **Pydantic** - Validación de datos
- **Integración visual experimental** - solo demo; no sustituye un proveedor de liveness

### Frontend
- **React 19** - Librería UI
- **TailwindCSS** - Estilos utilitarios
- **Radix UI** - Componentes accesibles
- **Axios** - Cliente HTTP

### Blockchain
- **Solidity 0.8.20 + OpenZeppelin 5** - Contrato SBT `DAOCiudadanaSBT` (soulbound, pausable, revocable)
- **ethers.js** - Interacción Web3 (integración MetaMask real en el frontend)
- **Contrato compatible desplegado:** ninguno; la dirección histórica de Sepolia usa otra ABI
- ⚠️ El minteo de producción está bloqueado hasta cerrar identidad y custodia de llaves

## 🎨 Interfaz

La portada y el onboarding usan la identidad cívica de EstamosDAO. Los estados
demo/off-chain se muestran de forma explícita y las capacidades on-chain solo se
anuncian cuando existe una transacción real.

## 🔒 Seguridad

Estado real de los controles (ver [AUDIT](./docs/AUDIT.md) para el detalle):

- ✅ **SBT no transferible** — soulbound aplicado en `_update` del contrato
- ✅ **CORS configurable** — sin comodín por defecto
- 🟡 **Rate limiting** con IP/proxy explícito y límite real de cuerpo; sigue en
  memoria de proceso y debe migrar a Redis antes de escalar horizontalmente
- ✅ **Autenticación SIWE** — requerida en minteo y acciones mutantes de gobernanza
- 🟡 **Gobernanza firmada** — propuestas con papeletas EIP-712 reverificables;
  votos de elecciones bloqueados en producción hasta implementar el mismo esquema
- 🟡 **PII de altas nuevas cifrada** — Fernet + índices HMAC; los documentos
  legacy aún requieren inventario, snapshot y migración antes de promover Atlas
- ✅ **Readiness fail-closed** — secretos, índices, modo y minteo condicionan `/health/ready`
- ⚠️ **Identidad** — falta el proveedor real y el grant de verificación de un solo uso
- ⚠️ **On-chain** — falta redesplegar el contrato compatible, custodiar el minter
  y añadir nonce distribuido + reconciliación idempotente con Mongo

## 🧪 Testing

```bash
# Backend
cd backend
pip install -r requirements-dev.txt
pytest -q
python -m pip_audit -r requirements.txt --strict

# Frontend
cd ../frontend
npm ci
npm run build

# Contratos
cd ../contracts
npm ci
npx hardhat test
```

## 📄 Licencia

MIT © 2024–2026 DAO Ciudadana
