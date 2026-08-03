# ADR 004: Verificación Criptográfica del SOD (CSCA y Document Signer)

## Estado
**Aceptado e implementado en Android (03-08-2026), sin ancla de confianza todavía.**

La lógica de los tres pasos vive en `PassiveAuthenticator.kt` y está cubierta por
`PassiveAuthenticatorTest` (6 casos con documentos sintéticos, incluido un documento
falsificado que trae su propia CSCA). **Falta el certificado CSCA de Chile**: mientras
`android/app/src/main/assets/csca/` no lo contenga, `identityVerified` es siempre `false`.

## Contexto
Durante la **Fase 4.2**, además de establecer el canal seguro vía PACE, es vital verificar la autenticidad e integridad de los datos extraídos de la cédula de identidad chilena. Los datos (Data Groups como el DG1 - MRZ y DG2 - Foto) están firmados (hacheados) en un archivo maestro llamado EF.SOD (Document Security Object).

La verificación de identidad electrónica requiere comprobar tres cosas:
1. **Passive Authentication (Autenticación Pasiva):** Que los hashes de los DGs (Data Groups) coincidan con los hashes firmados en el EF.SOD.
2. **Document Signer (DS):** Que la firma del EF.SOD haya sido realizada por un certificado DS válido.
3. **Country Signing Certificate Authority (CSCA):** Que el certificado DS esté firmado por la CSCA oficial del Estado de Chile (Registro Civil).

## Decisión Técnica

Para validar la cadena de confianza en la aplicación móvil, nos basaremos en los Módulos Nativos ya creados para PACE (`PassportReaderModule`), delegando también la verificación X.509 y CMS (Cryptographic Message Syntax) a las librerías nativas.

### Por qué en Nativo y no en JS:
- React Native no tiene soporte completo y nativo para analizar estructuras complejas ASN.1/CMS, necesarias para leer el EF.SOD.
- `react-native-quick-crypto` es rápido y eficiente para primitivas como SHA256 o RSA/ECDSA, pero requeriría dependencias JS adicionales pesadas (ej. `node-forge` o `pkijs`) para parsear los certificados X.509 de la CSCA y validar la cadena completa de confianza.
- Las librerías de eMRTD (como JMRTD en Android o NFCPassportReader en iOS) ya incluyen motores de validación completa de SOD y Master Lists.

### Arquitectura de Verificación

1. **Inclusión de la CSCA Chilena:**
   - La llave pública/certificado de la CSCA de Chile debe integrarse en la aplicación (empaquetada en la app o descargada de un endpoint de confianza del backend).
   - *Nota de seguridad:* Nunca debe confiarse en un certificado CSCA provisto por la propia tarjeta.

2. **Flujo en NativeModules (`PassportReader`):**
   - El módulo lee DG1, DG2 y SOD.
   - Extrae el certificado DS del SOD.
   - Comprueba que el DS está firmado por nuestro certificado CSCA chileno pre-configurado.
   - Comprueba la firma RSA/ECDSA del SOD usando la clave pública del DS.
   - Comprueba que los hashes de DG1 y DG2 coinciden con los declarados en el SOD.
   
3. **Retorno a React Native:**
   - JS recibe un JSON que incluye: `{ success: true, identityVerified: true, data: { ... } }`.
   - `identityVerified` solo será `true` si la validación criptográfica del SOD contra la CSCA fue exitosa.

## Librerías Criptográficas

- **Android:** Se usará `org.jmrtd:jmrtd` (que utiliza SpongyCastle/BouncyCastle internamente para la criptografía X.509 y firmas).
- **iOS:** Se usará `NFCPassportReader` (que usa OpenSSL embebido o CryptoKit nativo para la decodificación ASN.1 y validación criptográfica).
- **React Native:** Se mantiene `react-native-quick-crypto` en el entorno JS solo para compatibilidad legacy (BAC en entornos experimentales) o para preparar los payloads cifrados al backend, pero NO para parsear certificados.

## Riesgos y Mitigaciones
- **Rotación de CSCA:** El Registro Civil rota la llave maestra cada varios años. El backend de la DAO deberá exponer un endpoint `/api/csca-masterlist` para que la app móvil mantenga actualizada su raíz de confianza sin requerir una actualización en las tiendas de apps.
