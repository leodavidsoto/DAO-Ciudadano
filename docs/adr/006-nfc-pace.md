# ADR-006: Estrategia de implementación NFC y PACE para la Cédula de Identidad

> Renumerado el 08-08-2026: antes era **ADR-003** en `docs/adr/`, número que ya
> ocupaba otro ADR en `docs/`. El contenido no cambió.

## Estado
**Aceptado e implementado en Android (03-08-2026); iOS pendiente de dependencia.**

- Android: `PassportReaderModule.kt` ejecuta PACE con CAN vía JMRTD y lee DG1/DG2/EF.SOD.
- iOS: `PassportReader.swift` abre la sesión CoreNFC y detecta el chip, pero **no** hace PACE:
  la librería que este ADR eligió (`NFCPassportReader`) nunca se añadió al proyecto. Falla con
  `E_PACE_UNSUPPORTED_PLATFORM` en vez de simular una lectura.

## Contexto
La Fase 4.2 del Roadmap exige la lectura NFC real de la cédula de identidad chilena para extraer la información ciudadana, implementando el protocolo PACE (Password Authenticated Connection Establishment) sobre ISO-DEP, en lugar del obsoleto protocolo BAC. Posteriormente, se debe verificar la firma del SOD (Document Security Object) contra la CSCA (Country Signing Certificate Authority) de Chile.

La aplicación móvil está construida en React Native. Existen tres caminos principales para implementar la lectura del chip eMRTD (Documentos de viaje de lectura mecánica) con PACE:

1. **Implementación Pura en JavaScript / React Native:**
   - Usar `react-native-nfc-manager` para enviar APDUs crudos por `ISO-DEP`.
   - Implementar el mapeo de dominio PACE (Standardized Domain Parameters) y la derivación de claves ECDH usando `react-native-quick-crypto`.
   - **Contras:** Extremadamente complejo y propenso a errores. El mapeo de curva elíptica requerido por PACE no es trivial de implementar con primitivas criptográficas estándar de OpenSSL/Node.js sin capas adicionales. La validación del SOD requiere análisis ASN.1 y validación de cadena de certificados X.509 compleja.

2. **Módulo Nativo Propio (Envolturas de Librerías Nativas):**
   - **Android:** Crear un módulo nativo que envuelva `JMRTD` (Java Machine Readable Travel Document API), el estándar de facto open-source para Android.
   - **iOS:** Crear un módulo nativo que envuelva `NFCPassportReader` (Swift), una librería open-source popular para leer eMRTD con CoreNFC.
   - **Pros:** Usamos implementaciones criptográficas robustas, auditadas y probadas en el mundo real.
   - **Contras:** Requiere mantenimiento de código nativo en Kotlin y Swift.

3. **SDK Comercial (ReadID, Regula, etc.):**
   - Integrar un SDK de verificación de identidad de terceros.
   - **Pros:** SLA, alta fiabilidad, OCR incluido, liveness integrado (opcional).
   - **Contras:** Costo de licencias recurrente, dependencia de un proveedor (vendor lock-in), requiere revisión legal de protección de datos (si los datos viajan a los servidores del proveedor, rompiendo la filosofía de procesamiento local).

## Decisión Propuesta
**Descartamos la Opción 1** por riesgo técnico inaceptable. Intentar escribir un stack PACE/eMRTD desde cero en JS es reinventar la rueda en un dominio crítico para la seguridad y muy ajeno a las primitivas web estándar.

**Descartamos la Opción 3 (temporalmente)** debido a que el proyecto busca soberanía tecnológica y descentralización (Dao Ciudadano). Depender de un SDK de pago cerrado va en contra de la fase open-source actual, a menos que el Estado lo provea.

**Seleccionamos la Opción 2 (Módulos Nativos con Librerías Open Source):**
1. React Native se encargará de la UI (Captura de CAN, instrucciones al usuario).
2. Se construirá un puente (`NativeModules.PassportReader`) que, al recibir el CAN, invocará a Kotlin/Swift.
3. El código nativo ejecutará PACE, Secure Messaging y extraerá el DG1, DG2 (foto) y el SOD, retornando la información estructurada a JS.

## Siguientes Pasos Inmediatos (Implementación Frontend actual)
Dado que construir los puentes nativos y lidiar con JMRTD/Swift tomará tiempo, para la entrega de esta sesión (Fase 4.2 inicial) construiremos el "andamiaje" en React Native:
- **UI:** Pantalla para ingresar el CAN (manual o mock de OCR).
- **Service:** Interfaz `NfcService.ts` con los métodos `startPACESession(can)` listos para conectarse al módulo nativo.
- **Flujo:** Conectar la pantalla de onboarding existente con este nuevo flujo de validación NFC, mockeando la respuesta criptográfica para no bloquear el desarrollo del resto de la app.
