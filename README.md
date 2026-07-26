# 🏛️ DAO Ciudadana

> Sistema de membresía digital ciudadana basado en blockchain con verificación de identidad chilena

![Version](https://img.shields.io/badge/version-1.0.0-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![React](https://img.shields.io/badge/React-19-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-teal)

> ⚠️ **Estado actual (julio 2026): prototipo funcional con verificación simulada.**
> Los flujos de identidad (ClaveÚnica, NFC, liveness) y el minteo del SBT están
> en **modo demo** — el token todavía **no** se acuña on-chain (`totalSupply()` en
> Sepolia = 0) y la API aún no exige autenticación. Antes de exponerlo a usuarios
> reales, revisa el estado y el plan en [`docs/`](./docs):
> [AUDIT](./docs/AUDIT.md) · [ROADMAP](./docs/ROADMAP.md) · [HANDOFF](./docs/HANDOFF.md).

## 🎯 Descripción

DAO Ciudadana es una plataforma que permite a ciudadanos chilenos verificar su identidad y obtener un **Soulbound Token (SBT)** que representa su membresía en una organización autónoma descentralizada (DAO). El sistema soporta múltiples métodos de verificación:

- **ClaveÚnica**: SSO gubernamental chileno
- **NFC**: Lectura del chip de la cédula de identidad
- **Biometría IA**: Detección de vida con inteligencia artificial

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
yarn install
yarn start
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
└── contracts/              # Smart contracts (Hardhat) — SBT desplegado en Sepolia
```

## 🔌 API Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/auth/clave-unica` | POST | Autenticación ClaveÚnica |
| `/api/auth/nfc` | POST | Verificación NFC |
| `/api/auth/liveness` | POST | Detección de vida (IA) |
| `/api/wallet/connect` | POST | Conectar wallet |
| `/api/membership/mint` | POST | Mintear SBT |
| `/api/dashboard/stats` | GET | Estadísticas DAO |

## 🛠️ Stack Tecnológico

### Backend
- **FastAPI** - Framework async de alto rendimiento
- **MongoDB** (Motor) - Base de datos NoSQL
- **Pydantic** - Validación de datos
- **OpenAI GPT-4V** - Detección de vida con visión

### Frontend
- **React 19** - Librería UI
- **TailwindCSS** - Estilos utilitarios
- **Radix UI** - Componentes accesibles
- **Axios** - Cliente HTTP

### Blockchain
- **Solidity 0.8.20 + OpenZeppelin 5** - Contrato SBT `DAOCiudadanaSBT` (soulbound, pausable, revocable)
- **ethers.js** - Interacción Web3 (integración MetaMask real en el frontend)
- **Red actual:** Sepolia testnet · **Objetivo:** Polygon
- ⚠️ El minteo on-chain aún no está cableado desde el backend (ver ROADMAP Fase 1.5)

## 🎨 Tema Cyberpunk

La UI utiliza un tema cyberpunk con:
- Gradientes neón (cyan, magenta, verde)
- Efecto matrix rain de fondo
- Animaciones de glitch
- Tipografía Orbitron + Source Code Pro

## 🔒 Seguridad

Estado real de los controles (ver [AUDIT](./docs/AUDIT.md) para el detalle):

- ✅ **SBT no transferible** — soulbound aplicado en `_update` del contrato
- ✅ **CORS configurable** — sin comodín por defecto
- ✅ **Rate limiting** presente (en memoria de proceso; pendiente moverlo a Redis)
- ⚠️ **Autenticación** — aún no implementada en la API (ROADMAP Fase 1)
- ⚠️ **PII** — hoy se almacena sin cifrar; el hash de RUT no lleva sal (ROADMAP Fase 1.3/1.4)
- ⚠️ **Hashes on-chain** — todavía no se escribe nada en la cadena

## 🧪 Testing

```bash
# Backend tests
python backend_test.py

# Frontend tests
cd frontend && yarn test
```

## 📄 Licencia

MIT © 2024–2026 DAO Ciudadana
