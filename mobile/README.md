# DAO Ciudadana — aplicación móvil experimental

> Los builds nativos buscan ser reproducibles desde locks y toolchains fijados, pero
> la aplicación **no está lista para verificar identidad ni publicarse en los
> stores**. El puente iOS ya exige PACE y autenticación pasiva completa, pero
> falta una Master List chilena con procedencia autorizada y una prueba sobre
> cédula/dispositivo físicos. Sin esos dos gates la lectura falla cerrada.

La app usa React Native CLI 0.83, New Architecture y Hermes. No utiliza Expo,
EAS ni Fastlane: Android se compila con el Gradle Wrapper e iOS con
CocoaPods/Xcode.

## Toolchain fijado

| Componente | Versión |
|---|---:|
| Node.js | `22.22.2` (`.node-version`) |
| npm | `10.9.7` (`packageManager`) |
| React Native | `0.83.0` |
| Java | Temurin `17.0.18+8` en CI |
| Gradle | `9.6.1` en el wrapper actual; **incompatible y sin SHA** (P-85). `9.0.0` fue la última versión verificada |
| Android | SDK/target 36 · Build Tools 36.0.0 · NDK 27.1.12297006 · CMake 3.22.1 |
| Ruby | `3.3.12` (`.ruby-version`) |
| Bundler | `2.4.22` (`Gemfile.lock`) |
| CocoaPods | `1.15.2` (`Gemfile.lock`) |
| Xcode | `16.4` build `16F6` en `macos-15` |

`package-lock.json`, `Gemfile.lock`, `ios/Podfile.lock` y
`android/gradle/verification-metadata.xml` son parte del build. No deben
regenerarse implícitamente en CI.

El wrapper Android del árbol de trabajo no está verde: Gradle 9.6.1 falla por
incompatibilidad de metadata Kotlin. No se debe presentar el éxito obtenido
invocando un binario cacheado 9.0.0 como validación del wrapper; ver P-85.

## Instalación local

```bash
cd mobile
npm ci

# iOS: usa Ruby/Bundler de las versiones indicadas arriba.
bundle install
bundle exec pod install --project-directory=ios --deployment
```

Para desarrollo, la API conserva los loopbacks del simulador/emulador:

- Android: `http://10.0.2.2:8000/api`
- iOS: `http://localhost:8000/api`

```bash
npm run android
npm run ios
```

## Configuración obligatoria de Release

El bundle JavaScript inyecta la URL en compilación. Cualquier Release falla si
no recibe una URL HTTPS absoluta y sin credenciales:

```bash
export DAO_API_BASE_URL=https://api.example.cl/api
```

Los hosts de loopback están prohibidos. Un build de distribución también
rechaza el dominio reservado `.invalid`.

## Gates nativos de CI

`.github/workflows/ci.yml` ejecuta tres niveles sin exponer secretos a un PR:

1. gates estáticos: instalación con `npm ci`, auditoría crítica, TypeScript,
   ESLint con presupuesto de warnings y Jest;
2. Android Release **sin firma**, limitado a CI mediante una propiedad Gradle
   explícita; compila APK/AAB, lint y tests nativos con verificación estricta
   de dependencias, valida el AAB con el `bundletool` autenticado de AGP y
   comprueba alineación de página de 16 KiB;
3. iOS Release para dispositivo ARM64, sin code signing, desde `Podfile.lock`
   y el workspace generado con `pod install --deployment`.

Ambos jobs guardan artefactos y SHA-256 durante siete días. Estos binarios sin
firma son evidencia de compilación/autolinking, no entregables instalables.

Comandos equivalentes:

```bash
DAO_API_BASE_URL=https://mobile-ci.invalid/api \
CI=true npm run android:ci

DAO_API_BASE_URL=https://mobile-ci.invalid/api \
npm run ios:ci
```

## Release firmado

`.github/workflows/mobile-release.yml` se activa manualmente o con un tag
`mobile-vX.Y.Z` que coincida con `package.json`. Solo acepta commits contenidos
en `main`, usa environments protegidos y nunca publica automáticamente a una
tienda. Produce:

- Android: APK + AAB firmados, lint y checksums;
- iOS: IPA + dSYMs, entitlements extraídos y checksums.

Variables públicas de los environments:

```text
MOBILE_API_BASE_URL
IOS_BUNDLE_IDENTIFIER
IOS_TEAM_ID
ENABLE_MOBILE_ATTESTATION (opcional para repos privados Enterprise Cloud)
```

Secrets de `mobile-android-release`:

```text
DAO_ANDROID_KEYSTORE_BASE64
DAO_ANDROID_KEYSTORE_PASSWORD
DAO_ANDROID_KEY_ALIAS
DAO_ANDROID_KEY_PASSWORD
DAO_ANDROID_CERT_SHA256
```

Secrets de `mobile-ios-release`:

```text
IOS_CERTIFICATE_P12_BASE64
IOS_CERTIFICATE_PASSWORD
IOS_CERTIFICATE_SHA256
IOS_PROVISIONING_PROFILE_BASE64
IOS_KEYCHAIN_PASSWORD
IOS_CSCA_MASTER_LIST_BASE64
IOS_CSCA_MASTER_LIST_SHA256
```

`ios/ExportOptions.plist` fija una exportación manual a App Store Connect; el
workflow agrega únicamente el Team ID y el nombre del profile ya validado.

El certificado, profile y keystore se crean únicamente dentro de
`$RUNNER_TEMP`, se contrastan con sus valores esperados y se eliminan incluso
si el build falla. Los environments deben exigir aprobación humana.

La Master List CSCA también entra únicamente desde el environment protegido.
Su PEM se contrasta con `IOS_CSCA_MASTER_LIST_SHA256`, se valida antes de
copiarlo al bundle y el IPA exportado vuelve a comprobar la misma huella. No
uses los `masterList.pem` de ejemplo de `NFCPassportReader`: uno es un
certificado de prueba y el otro no conserva procedencia/licencia verificable
del dataset ICAO.

Para un build iOS local con el artefacto ya autorizado:

```bash
export DAO_CSCA_MASTER_LIST_PATH=/ruta/privada/csca-chile.pem
export DAO_CSCA_MASTER_LIST_SHA256=<huella-obtenida-por-segundo-canal>
export DAO_MOBILE_DISTRIBUTION=true
```

Sin esas variables, desarrollo omite el recurso y el lector falla cerrado;
distribución detiene el build.

En repos públicos se emite además una attestation Sigstore/GitHub de los
artefactos. En repos privados se activa explícitamente con
`ENABLE_MOBILE_ATTESTATION=true` solo cuando la organización dispone de GitHub
Enterprise Cloud; el checksum permanece siempre disponible.

Una firma incorpora certificados y timestamps, por lo que dos IPA/APK firmados
no tienen por qué ser idénticos byte a byte. Aquí “reproducible” significa:
fuente inmutable, dependencias bloqueadas y verificadas, toolchain/versiones
fijados, compilación limpia, firma externa y checksum/procedencia del artefacto.

## Firma Android local

El build nunca cae a la llave debug. Además de la URL y las versiones, exige:

```bash
export DAO_ANDROID_KEYSTORE_FILE=/ruta/privada/dao-ciudadana-release.jks
export DAO_ANDROID_KEYSTORE_PASSWORD='...'
export DAO_ANDROID_KEY_ALIAS='...'
export DAO_ANDROID_KEY_PASSWORD='...'
export DAO_VERSION_NAME=1.0.0
export DAO_VERSION_CODE=1
export DAO_API_BASE_URL=https://api.example.cl/api
export DAO_MOBILE_DISTRIBUTION=true

npm run android:release
```

`*.keystore`, `*.jks`, `*.p12`, Pods y productos nativos están ignorados.

## NFC

Android obtiene `android.permission.NFC` y la feature opcional desde
`react-native-nfc-manager`. iOS incluye `NFCReaderUsageDescription`, el AID
eMRTD, el entitlement `NDEF`/`TAG` y el privacy manifest dentro del target.

El bridge iOS sólo entrega `identityVerified: true` si se estableció PACE-CAN,
se leyeron DG1/DG2/EF.SOD, el emisor y perfil corresponden a una cédula chilena,
el documento está vigente, los hashes coinciden, la firma del SOD valida y el
Document Signer encadena con una CSCA chilena provisionada. Esto autentica los
datos firmados, pero todavía no consulta revocación, no ejecuta AA/CA para
descartar clonación y no compara DG2 con un liveness autorizado. La versión del
fork iOS que acepta CAN tampoco tiene prueba física chilena reproducible; por
eso no se declara Fase 4.2 completa.

Antes de una publicación también debe confirmarse con el responsable de datos
si la dirección de wallet se retiene o vincula a una identidad y ajustar
`PrivacyInfo.xcprivacy` en consecuencia.
