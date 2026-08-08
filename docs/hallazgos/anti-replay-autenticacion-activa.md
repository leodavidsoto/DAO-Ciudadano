# Hallazgos — Autenticación Activa (anti-replay)

Revisión adversaria del 08-08-2026 sobre el trabajo sin commitear del carril
`identidad`. Contraste contra ICAO 9303-11 y BSI TR-03111, no contra los
fixtures del autor.

**Veredicto: fusionar con correcciones.** La criptografía es correcta. El
cliente móvil no está cableado, y eso es bloqueante para desplegar.

## Lo que está bien

| Punto | Veredicto | Evidencia |
|---|---|---|
| RSA por ISO/IEC 9796-2 DS1, no PKCS1v15 | ✅ | `active_auth.py:248-320`; prueba las dos raíces F\* y n−F\* en `:343-350`, que es lo que exige B.7 |
| Vector de prueba de un tercero | ✅ | `test_active_auth.py:41-70` es el `doTest13` de `ISO9796Test.java` de BouncyCastle, con procedencia verificada contra `bcgit/bc-java`. Ancla en las dos direcciones: el verificador acepta una firma que no calculó, y el firmante del fixture la reproduce byte a byte |
| Regresión de PKCS1v15 fijada | ✅ | `test_active_auth.py:110-121` — el fallo de `bdb78cf` no puede volver en silencio |
| Desafío emitido por el servidor | ✅ | `cedula.py:104-118`, 8 bytes de `secrets.token_bytes`. El modelo de entrada no admite un desafío propio del cliente |
| Consumo atómico y de un solo uso | ✅ | `aa_challenge.py:133-136`, `find_one_and_update` con filtro por estado; índice único en `database.py`. Se quema **antes** de verificar |
| DG15 ligado al hash que firmó el SOD | ✅ | `passive_auth.py:425-446` comprueba todos los DG recibidos; `cedula_nfc.py:257-265` exige además DG15 verificado. Dos tests cubren el ataque de clave propia |
| Test de captura reenviada | ✅ | `test_cedula_active_auth.py:197-216`, reenvío byte a byte → 401. Y `:219-241`, firma capturada contra desafío fresco → 401 |
| Falla cerrado en el backend | ✅ | Política exigida sin firma, chip sin DG15, desafío desconocido/quemado/expirado: 401 en todos |

## Bloqueante — el cliente móvil no usa la feature

Con la política por defecto (`config.py:318-329` → exige AA en producción),
**toda alta desde la app real recibiría 401** el día del despliegue.

1. Nadie llama a `POST /auth/cedula/aa-challenge`. `ActiveAuthChallenge` está
   declarada en `nfcService.ts:56-61` y nunca se construye.
2. `startPACESession` se declara con cuatro argumentos (`nfcService.ts:40-45`)
   y se llama con tres (`nfcService.ts:826`): `aaChallenge` llega indefinido.
   En iOS el desajuste de firma **no falla en compilación, falla en ejecución**.
3. `apiService.verifyCedula` sigue enviando solo DG1 y DG2
   (`apiService.ts:104-109`): ni `dg15`, ni `dg14`, ni `active_authentication`.
4. `ScanScreen.tsx:155` sigue llamando al flujo antiguo.

## Correcciones pendientes, por severidad

**Alta — `CEDULA_REQUIRE_ACTIVE_AUTH=false` reabre el replay sin dejar rastro.**
En producción esa variable devuelve `False` y el camino pasivo vuelve a emitir
grants. Contrasta con la disciplina de `CSCA_TRUST_STORE_PATH`
(`config.py:216-224`: «no hay valor que la desactive»), y `readiness.py` no
expone la política, así que un despliegue degradado no lo señala en ningún
sitio.

**Media — la rama ECDSA no está anclada a ningún vector publicado.**
`test_active_auth.py:241-285` y el fixture de `emrtd_fixtures.py:499-510` firman
y verifican con la misma librería y la misma convención: si el formato plano
`r‖s` de TR-03111 estuviera mal entendido, ambos lados compartirían el
malentendido y los tests seguirían en verde. Es literalmente el patrón de la
regla 11. Riesgo real bajo —las cédulas chilenas actuales usan RSA— pero hay
que cerrarlo.

**Media — la atomicidad del desafío no está probada.** El único test de
unicidad es secuencial (`test_cedula_active_auth.py:124-129`) y la suite corre
sobre `mongomock_motor`. Falta un test de consumo concurrente.

**Baja — el parser DS1 es más laxo que el estándar.** Comprobado ejecutando el
código: acepta un tráiler explícito cuyo último byte no es `0xCC` (`:276`
comprueba solo el nibble), acepta relleno que no es `0xBB` (`:298-300`) y
acepta la cabecera de recuperación total `0x4A`, cuando la AA de ICAO siempre
es parcial. Ninguna es explotable sin la clave privada, pero son desviaciones.

**Baja — sin suelo de tamaño de clave.** `parse_dg15` acepta RSA de 512 bits
(comprobado). Mitigado porque DG15 va ligado al SOD, así que la clave la elige
Chile y no el atacante.

**Baja — diagnóstico enmascarado.** Cuando la Autenticación Pasiva local falla,
el nativo deja `performed: true` y omite la firma
(`PassportReaderModule.kt:567`, `PassportReader.swift:311`), así que el parser
devuelve `null` y el usuario ve `E_INVALID_NATIVE_RESPONSE` en vez del motivo
verdadero.
