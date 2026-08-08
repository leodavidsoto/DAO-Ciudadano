# Prompt — Anti-replay de la cédula (Autenticación Activa)

> Pégale esto a un agente nuevo en `/Users/mac/DAO-Ciudadano`.

---

Lee `AGENTS.md` antes de tocar código. Trabajas en la rama `codex/produccion-ci`.

## El problema

`backend/app/services/cedula_nfc.py` lo declara en su propia cabecera, sin
mitigar:

> La Autenticación Pasiva demuestra que los datos los firmó Chile. **NO demuestra
> que el chip esté presente ahora.** Quien consiga los bytes de un SOD y sus DG
> —leyendo la cédula ajena con el CAN, o interceptando un payload— puede
> reenviarlos y obtener un grant para ESE titular.

Desde esta semana ese camino **funciona de verdad**: se dio de alta a una persona
real contra anclas CSCA del Registro Civil. O sea que el agujero pasó de teórico
a explotable. Un `curl` con bytes capturados obtiene hoy una membresía a nombre
de otro.

## Tu tarea

Autenticación Activa (ICAO 9303): el chip firma un desafío con una llave privada
que no puede extraerse. Eso prueba presencia física del chip, no solo que los
datos sean auténticos.

## Lo que ya existe, y por qué NO puedes fiarte de ello

Hay un commit **sin fusionar**, `bdb78cf`, en la rama
`subagent-Backend-Cryptographer-backend-agent-43808001`:

```
backend/app/services/active_auth.py | 63 ++++
backend/tests/test_active_auth.py   | 96 ++++
```

**Su rama RSA está mal para chips reales.** El propio comentario lo admite:

> «In a real ICAO 9303 implementation for RSA, ISO/IEC 9796-2 Scheme 1 is used.
> For this backend logic and test compatibility, we use standard PKCS1v15…»

La Autenticación Activa de un eMRTD usa **ISO/IEC 9796-2 Digital Signature
Scheme 1**, con recuperación de mensaje. Con PKCS1v15 **ninguna cédula real
validará jamás**. Y sus 96 líneas de tests pasan porque se escribieron contra la
misma suposición equivocada.

Esto es exactamente lo que ya pasó dos veces este mes (P-97 y P-101): el fixture
reproducía el error en vez de detectarlo, y cientos de tests en verde no vieron
nada. Úsalo como punto de partida, **no como base validada**.

## Lo que hay que construir

### 1 · El desafío lo genera el SERVIDOR y es de un solo uso

Si el desafío lo elige el teléfono, no hay anti-replay: quien capturó unos bytes
puede capturar también una firma y reusarla. Necesitas un endpoint que emita un
desafío aleatorio de 8 bytes, lo guarde con TTL corto, y lo queme al consumirlo.

Mira `backend/app/services/membership_grant.py` como patrón: ya resuelve
emisión, reclamo y quema de un solo uso, con sus índices en Mongo.

### 2 · El lado nativo

Ninguno de los dos lectores hace AA hoy. Hace falta:

- Leer **EF.DG15** (la llave pública de AA). Si el documento no lo trae, no
  admite AA y hay que decirlo, no fingirlo.
- Enviar `INTERNAL AUTHENTICATE` con el desafío del servidor.
- Devolver DG15 y la firma **en crudo, base64**, junto a los archivos que ya se
  mandan.

```
mobile/android/app/src/main/java/com/daociudadanaapp/PassportReaderModule.kt
mobile/ios/DAOCiudadanaApp/PassportReader.swift
mobile/ios/DAOCiudadanaApp/PassportReader.m        (firma del puente)
mobile/src/services/nfcService.ts                  (RawDocumentFiles, parseo estricto)
```

Ojo: `RawDocumentFiles` valida base64 estricto y **falla cerrado** si falta
cualquier archivo. Sigue ese patrón — que un DG15 ausente no pase como válido.

### 3 · Verificación en el servidor

- ISO/IEC 9796-2 Scheme 1 para RSA. Para ECDSA, ICAO usa el hash indicado en
  DG14/SecurityInfos.
- Comprobar que el hash de DG15 cuadra con el que el SOD firmó. **Sin esto la AA
  no sirve de nada**: un atacante pondría su propia llave pública y firmaría con
  ella.
- Consumir el desafío. Si ya se usó, rechazar.

### 4 · Nivel de aseguramiento

Hoy el grant declara `CEDULA_NFC_PASSIVE` — el nombre dice exactamente lo que se
comprobó, y eso está bien. Con AA, el nivel debe subir (`CEDULA_NFC_ACTIVE` o
similar) y `membership_grant` debe transportarlo. Mira cómo lo hace hoy
`backend/app/routers/cedula.py`.

Decide con el dueño si producción **exige** AA o solo la registra. Si la exige,
las cédulas sin DG15 dejan de poder darse de alta: es una decisión de política,
no técnica.

## Cómo probarlo de verdad

Hay una cédula chilena física disponible y el camino completo funciona
(`docs/PRODUCCION_SEPOLIA.md`). Contra ella se descubrió que dos supuestos
«verificados» eran falsos.

**Antes de dar esto por hecho, comprueba las dos direcciones:**

1. Una lectura real con AA produce un grant de nivel elevado.
2. **Reenviar los mismos bytes capturados es rechazado.** Sin esta segunda
   prueba no has demostrado nada: es literalmente el ataque que cierras.

## Reglas que no puedes saltarte

- `AGENTS.md` regla 5: no simules capacidades que no existen. Si el chip no
  admite AA, dilo; no devuelvas «verificado» por defecto.
- Regla 2: si arreglas un mock, bórralo.
- Regla 3: no marques nada completo sin ejecutar el camino real.
- El RUN nunca entra en un log. Si necesitas depurar, registra **forma, no
  valor**: `cedula_nfc.describe_field_shape()` ya lo hace así.
- Todo hallazgo va a `docs/AUDIT.md` con `archivo:línea` y severidad.

## Criterios de aceptación

1. Un desafío emitido por el servidor, de un solo uso, con TTL corto.
2. Verificación ISO/IEC 9796-2 Scheme 1 real, con vectores de prueba de ICAO
   9303 — no inventados por ti ni derivados de tu propia implementación.
3. La llave de DG15 se comprueba contra el hash que firmó el SOD.
4. Reenviar una captura es rechazado, demostrado con una prueba explícita.
5. `cd backend && ./.venv/bin/python -m pytest -q` en verde (hoy: 578).
6. `docs/AUDIT.md` actualizado, incluido lo que no lograste probar.
