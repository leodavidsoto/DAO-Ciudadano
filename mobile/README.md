# DAO Ciudadana - Mobile App (experimental)

> **No distribuir como release.** La lectura PACE/ISO-DEP de la cédula no está
> implementada y CI solo valida TypeScript, lint, tests y dependencias: todavía
> no produce un artefacto nativo. La lectura NDEF actual detecta tags, pero no
> verifica identidad. Configurar una firma Android
> tampoco convierte este piloto en una aplicación lista para producción.

Prototipo React Native para investigar el flujo móvil y NFC.

## Requisitos

- Node.js 20.19.4+
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

## Firma de Android release

`release` nunca usa la llave debug. El build falla de forma explícita si falta
alguna de estas variables o si la ruta no apunta a un keystore legible:

```bash
export DAO_ANDROID_KEYSTORE_FILE=/ruta/privada/dao-ciudadana-release.jks
export DAO_ANDROID_KEYSTORE_PASSWORD='...'
export DAO_ANDROID_KEY_ALIAS='...'
export DAO_ANDROID_KEY_PASSWORD='...'

cd android
./gradlew assembleRelease
```

El keystore y sus contraseñas deben guardarse en un gestor de secretos, fuera
del repositorio. Los formatos `*.keystore`, `*.jks` y `*.p12` están ignorados.
La firma permite producir un artefacto instalable, pero no elimina los bloqueos
funcionales y de seguridad descritos al inicio.

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

Esta rama apunta al backend local: `10.0.2.2:8000/api` desde el emulador Android
y `localhost:8000/api` desde el simulador iOS. Todavía no existe una selección
de entorno/base URL apta para un release; debe resolverse antes de publicar.

## Smart Contract

No hay un contrato compatible configurado. La dirección Sepolia histórica usa
otra ABI y no debe reutilizarse.
