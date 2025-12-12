# 🏛️ DAO Ciudadana

> Sistema de membresía digital ciudadana basado en blockchain con verificación de identidad chilena

![Version](https://img.shields.io/badge/version-1.0.0-cyan)
![License](https://img.shields.io/badge/license-MIT-green)
![React](https://img.shields.io/badge/React-19-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-teal)

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
└── contracts/              # (Future) Smart contracts
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

### Blockchain (Futuro)
- **Solidity** - Smart contracts
- **ethers.js** - Interacción Web3
- **Polygon** - Red L2

## 🎨 Tema Cyberpunk

La UI utiliza un tema cyberpunk con:
- Gradientes neón (cyan, magenta, verde)
- Efecto matrix rain de fondo
- Animaciones de glitch
- Tipografía Orbitron + Source Code Pro

## 🔒 Seguridad

- ✅ Solo hashes criptográficos on-chain
- ✅ SBT no transferible
- ✅ Datos PII nunca expuestos
- ✅ Rate limiting implementado
- ✅ CORS configurado

## 🧪 Testing

```bash
# Backend tests
python backend_test.py

# Frontend tests
cd frontend && yarn test
```

## 📄 Licencia

MIT © 2024 DAO Ciudadana
