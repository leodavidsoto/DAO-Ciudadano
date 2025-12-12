# DAO Ciudadana - Mobile App

App móvil React Native para lectura de chip NFC de cédula chilena.

## Requisitos

- Node.js 20+
- Android Studio (para Android)
- Xcode (para iOS)
- Dispositivo con NFC

## Instalación

```bash
cd mobile
npm install

# iOS
cd ios && pod install && cd ..

# Android
# Asegúrate de tener Android SDK configurado
```

## Ejecutar

```bash
# Android
npm run android

# iOS
npm run ios
```

## Permisos NFC

### Android
Los permisos NFC se configuran en `android/app/src/main/AndroidManifest.xml`

### iOS
NFC requiere configuración adicional en Xcode:
1. Agregar capability "Near Field Communication Tag Reading"
2. Agregar `NFCReaderUsageDescription` en Info.plist

## Estructura

```
mobile/
├── src/
│   ├── screens/       # Pantallas de la app
│   ├── services/      # NFC y API
│   ├── hooks/         # Custom hooks
│   └── components/    # Componentes UI
├── App.tsx            # Entry point
└── package.json
```

## Backend API

La app se conecta a: `https://dao-ciudadana-api.onrender.com`

## Smart Contract

Contrato SBT en Sepolia: `0x813fd379F715107b2451553d97f29408d8185f0e`
