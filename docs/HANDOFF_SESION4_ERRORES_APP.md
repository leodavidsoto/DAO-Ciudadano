# Handoff Sesión 4 — Errores de la app en dispositivo real

Punto de partida para el siguiente agente. Recoge tres defectos observados en un
teléfono real con una cédula chilena real, y un problema de proceso que hay que
resolver **antes** de tocar código.

---

## 0. LEE ESTO PRIMERO — hay dos agentes editando los mismos archivos

Durante esta sesión, otro agente reescribió estos archivos mientras yo trabajaba:

| Archivo | Modificado | Yo trabajé a las |
| --- | --- | --- |
| `mobile/src/screens/ScanScreen.tsx` | 04:47 | 03:05 |
| `mobile/src/services/nfcService.ts` | 04:46 | 03:05 |

**Consecuencia medida ahora mismo:**

```
npx tsc --noEmit   → error TS2724: '"../nfcService"' has no exported member
                     named 'PACE_CAN_LENGTH'. Did you mean 'PACE_CAN_MAX_LENGTH'?
npx jest           → Test Suites: 2 failed, 3 passed
                     Tests: 16 failed, 58 passed, 74 total
```

Las puertas de mobile estaban en verde a las 03:12 (74/74, tsc limpio, 0 errores
de lint). **Ahora están rojas.** No es una regresión de los arreglos de abajo:
es el cambio de diseño del otro agente, que no vino con tests.

### Qué cambió ese agente

Pivotó la clave del canal seguro:

- Antes: CAN de **6 dígitos numéricos** (`PACE_CAN_LENGTH = 6`).
- Ahora: **Número de Documento alfanumérico de 6 a 15** (`PACE_CAN_MAX_LENGTH = 15`),
  más dos campos nuevos de **fecha de nacimiento** y **fecha de vencimiento**
  (`readChileanIDPACE(can, dob, doe)`), que es la entrada de una clave tipo BAC.

Ojo: la sesión anterior había **borrado** `bacCrypto.ts` por código muerto, y
esto reintroduce la derivación por MRZ. Puede estar bien —una cédula que no
publique CAN necesita ese camino— pero es una decisión de arquitectura que
nadie ha ratificado y que contradice el mensaje de `E_PACE_UNSUPPORTED`, que
todavía dice *«No se acepta el respaldo BAC»*. **Aclara esto antes de seguir.**

**Coordina con el dueño antes de editar `ScanScreen.tsx` o `nfcService.ts`.**

---

## 1. Layout roto — el formulario se pinta encima del título ❌ SIN ARREGLAR

En las dos capturas, «LECTURA eMRTD» queda tapado por cajas vacías y el círculo
del escáner se solapa con todo.

**Causa (diagnóstico firme, no hipótesis):** `ScanScreen.tsx:405`

```js
scannerContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' }
```

Ese contenedor ahora guarda **tres campos con etiqueta y ayuda** (documento,
fecha de nacimiento, fecha de vencimiento) **más** el círculo de ~220px. El
contenido mide más que el espacio disponible, y en flexbox un hijo centrado que
desborda **se sale por los dos lados a la vez**. Como la pantalla no tiene
`ScrollView`, lo que se sale por arriba se pinta sobre el header.

Antes no pasaba porque solo había un campo.

**Arreglo propuesto:** envolver el contenido de `SafeAreaView` en un
`ScrollView` con `contentContainerStyle={{ flexGrow: 1 }}` y quitar el
`justifyContent: 'center'` de `scannerContainer`. Con tres campos y un teclado
abierto, esta pantalla ya no cabe en un teléfono pequeño: necesita scroll de
verdad, no un centrado más apretado.

No lo apliqué por el punto 0.

---

## 2. «Tag was lost» se reportaba como CAN equivocado ✅ ARREGLADO (sin probar en dispositivo)

**Lo que se vio (captura 1):**

```
IOException -> CardServiceException: Read binary failed on file 11c
            -> CardServiceException: Could not tranceive APDU
            -> TagLostException: Tag was lost
```

…y la app respondió *«No se pudo abrir el canal seguro — la causa más frecuente
es un CAN equivocado. Revisa los dígitos.»*

**Eso es un diagnóstico falso.** El fichero `0x011C` es **EF.CardAccess**, que se
lee *antes* de PACE para obtener sus parámetros. O sea: la cédula se despegó del
teléfono al principio de la lectura. El CAN nunca llegó a probarse. Se le decía
al ciudadano que revisara unos dígitos que estaban bien.

**Origen:** `PassportReaderModule.kt` tenía un `catch (e: Throwable)` que mandaba
**todo** como `E_PACE_FAILED`, y `nfcService.ts` mapea ese código a
`action: 'fix_can'`.

**Lo que cambié:**

- `PassportReaderModule.kt:596` — nuevo `isTagLost(e)`, que recorre la cadena de
  causas (JMRTD envuelve la `TagLostException` dentro de `CardServiceException`
  dentro de `IOException`; mirar solo la excepción de arriba no la ve).
- `PassportReaderModule.kt:175` — emite `E_TAG_LOST` en vez de `E_PACE_FAILED`
  cuando la causa es esa.
- `nfcService.ts:507` — caso `E_TAG_LOST` → *«La cédula se separó del teléfono»*,
  `action: 'retry_positioning'`. El texto no afirma que el canal llegara a
  abrirse, porque puede caerse antes o después de PACE.

**Pendiente:** compilar el APK y confirmarlo en el teléfono. **No hay test que
cubra `E_TAG_LOST`** — añádelo en `nfcService.test.ts` junto a los demás códigos.

---

## 3. El servidor rechaza la cédula: no encuentra el RUN ❌ SIN RESOLVER (falta un dato)

**Lo bueno:** la captura 2 demuestra que **el flujo completo funciona**. El chip
se leyó, los archivos en crudo viajaron a `POST /api/auth/cedula/verify`, el
servidor repitió la Autenticación Pasiva y contestó 401 con su razón. La app la
mostró tal cual, sin parafrasear, y no emitió ninguna credencial. Esa parte hace
exactamente lo que debe.

**Lo que bloquea el alta:**

> La MRZ del documento no expone un RUN reconocible. No se deriva una identidad
> de un campo que no se sabe interpretar.

**Recorrido del dato:**

- `backend/app/services/mrz.py:179` — TD1: `optional_data = line1[15:30]`, con el
  comentario *«El RUN de la cédula chilena viaja aquí»*.
- `backend/app/services/cedula_nfc.py:224` — `run = normalize_run(mrz.optional_data)`.
- `backend/app/services/cedula_nfc.py:78` — el patrón que no casó:
  ```python
  _RUN_PATTERN = re.compile(r"^(?P<body>[0-9]{6,8})-?(?P<check>[0-9K])$")
  ```

**No sé por qué falló, y no voy a adivinarlo.** Un RUN de 9 caracteres sin guion
(`123456789`) sí casa con ese patrón, así que el contenido real de ese campo es
algo distinto de lo que el código supone. Hipótesis a descartar, en orden:

1. El campo va **vacío** en la cédula chilena y el RUN vive en **DG11 o DG13**,
   no en la MRZ. (Es la más probable y la más cara: cambia qué data groups hay
   que pedirle al chip.)
2. Lleva el RUN **más un dígito de control del propio campo opcional**, con lo
   que sobra un carácter y el `$` del patrón no cierra.
3. El teléfono manda el DG1 recortado o con relleno distinto, y `line1[15:30]`
   no cae donde creemos.

**Cómo averiguarlo sin registrar el RUN de nadie.** Este backend nunca guarda el
RUN a propósito, y así debe seguir. Añade un log que revele **forma, no valor**:
longitud del campo y máscara de clases de carácter (p. ej. `"len=14 DDDDDDDDD<<<<<"`).
Con eso se distingue entre las tres hipótesis sin escribir el número en ningún
sitio. Bórralo en cuanto se sepa la respuesta.

**No inventes un RUN ni relajes el patrón para que pase.** El dígito verificador
se comprueba justamente porque de ese número cuelga la identidad entera de la
persona (ver el docstring de `normalize_run`). Aflojarlo para desbloquear la
demo es exactamente lo que `AGENTS.md` prohíbe.

---

## Estado del repositorio

**Commiteado** (`e99e8d6`, rama `codex/produccion-ci`): solo
`docs/HANDOFF_ANTIGRAVITY_SESION3.md`.

**Sin commitear:** todo lo demás — los arreglos de mobile de la sesión 4, los de
esta sesión (`E_TAG_LOST` en Kotlin y TypeScript), `backend/tests/test_membership_grant.py`,
`contracts/tasks/` y `mobile/src/context/`.

**Puertas ahora mismo:**

| Puerta | Estado |
| --- | --- |
| Backend `pytest -q` | ✅ 566 pasan |
| Contratos `npx hardhat test` | ✅ 59 pasan |
| Mobile `npx jest` | ❌ **16 fallan**, 58 pasan |
| Mobile `tsc --noEmit` | ❌ 1 error (`PACE_CAN_LENGTH`) |

---

## Orden sugerido para el siguiente agente

1. **Resolver el punto 0.** Decidir si el pivote a documento+fechas se queda. Si
   se queda, actualizar `nfcService.test.ts` y `ScanScreen.test.tsx` a la nueva
   entrada (ahí están los 16 fallos) y corregir el mensaje de
   `E_PACE_UNSUPPORTED`, que sigue negando BAC.
2. **Arreglar el layout** (punto 1). Es lo que más se nota y no depende de nadie.
3. **Cubrir `E_TAG_LOST` con un test** y verificarlo en el teléfono.
4. **Instrumentar `optional_data`** con el log de forma y volver a escanear la
   cédula real. Sin ese dato, el punto 3 no avanza.
