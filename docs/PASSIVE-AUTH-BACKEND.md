# Autenticación Pasiva real en el servidor (Fase 5.8)

Estado: **backend terminado y probado; el móvil todavía no manda los bytes.**
El flujo completo no funciona hasta que se cierre la parte de Codex descrita
más abajo.

---

## 1. Qué había antes

Dos cosas, y ninguna verificaba identidad:

* `POST /api/auth/nfc` devolvía `ok: true` con un `chip_serial` derivado de lo
  que el cliente mandara —o de un UUID aleatorio si no mandaba nada— y un
  `doc_hash` derivado de ese serial. No leía ningún chip. Acreditaba identidad
  a cualquiera que llamase al endpoint con `curl`.
* El móvil **sí** hacía Autenticación Pasiva de verdad
  (`PassiveAuthenticator.kt`), pero el resultado se quedaba en el teléfono. La
  carpeta `assets/csca/` estaba vacía, así que en la práctica devolvía siempre
  `identityVerified: false` con el motivo "no hay ningún certificado CSCA
  instalado".

La verificación del móvil es correcta y sigue ahí: le dice a la persona, en el
momento, si su cédula es auténtica. Lo que no puede ser es la base de una
decisión del servidor — un booleano dentro de un JSON es una afirmación del
cliente, no una prueba.

## 2. Qué hay ahora

### 2.1 Los certificados del Registro Civil

`backend/scripts/extract_csca_from_ldif.py` extrae las CSCA de un país desde el
LDIF del PKD de la ICAO. El archivo `icaopkd-002-complete-527` **no** contiene
certificados sueltos: contiene *master lists* (`pkdMasterListContent;binary`),
cada una un CMS SignedData cuyo contenido encapsulado es la estructura
`CscaMasterList` de ICAO 9303-12. Hay que abrir dos capas de ASN.1 antes de ver
un X.509.

Resultado para Chile — **9 certificados**, todos del Servicio de Registro Civil
e Identificación, que forman cinco generaciones encadenadas:

| Gen | Raíz auto-firmada (ancla) | Vigencia | Eslabón de rotación |
|---|---|---|---|
| 1 | `4c2daca0fb8d73e1` | 2013-08-01 → 2029-11-16 | — |
| 2 | `89f6143b835c2a41` | 2016-08-01 → 2032-11-16 | `f88b2c0769cf975a` (firmado por gen 1) |
| 3 | `bd10b0cf3addd12c` | 2021-08-01 → 2037-11-16 | `7585ae3201e93ce4` (firmado por gen 2) |
| 4 | `26539f4a222aec83` | 2024-05-28 → 2039-06-13 | `69a22617cc39b11d` (firmado por gen 3) |
| 5 | `b5dd74579cd7db82` | 2026-05-05 → 2051-05-20 | `8e82732a4449b7fc` (firmado por gen 4) |

Salidas:

* `backend/app/certs/csca_chile.pem` — las 5 anclas **más** los 4 eslabones,
  con cabeceras legibles (subject, issuer, vigencia, huella, corroboración).
* `mobile/android/app/src/main/assets/csca/*.pem` — sólo las 5 anclas, un
  archivo por certificado, que es lo que espera el cargador de la app.

**La trampa que casi se cuela.** El criterio habitual para distinguir una raíz
es `subject == issuer`. Aquí es **incorrecto**: desde la 4ª generación el
Registro Civil rota la clave conservando el mismo DN, así que sus link
certificates tienen subject idéntico al issuer. Con la prueba por DN, el
eslabón `8e82732a4449b7fc` se clasificaba como ancla — un certificado
intermedio ascendido a raíz de confianza. Tanto el script como el cargador del
backend como el del móvil clasifican ahora **verificando la firma con la propia
clave pública**, que es la definición criptográfica y no se deja engañar.

No se verifica la firma de las master lists: sólo se podría hacer contra la
CSCA del país emisor, que es justo lo que se está intentando obtener. La
confianza viene del canal (descarga del PKD). Lo que sí se hace es contar en
cuántas master lists **de emisores distintos** aparece cada certificado, y
reportarlo: las generaciones 1-4 aparecen en 8-11 master lists independientes;
la 5ª, por reciente, en 2.

### 2.2 La verificación

`backend/app/services/passive_auth.py` repite la Autenticación Pasiva completa
sobre los bytes crudos. Cuatro comprobaciones, todas obligatorias:

1. La firma del EF.SOD verifica con la clave pública del Document Signer.
2. El `messageDigest` de los `signedAttrs` corresponde al eContent presente.
3. Los hashes de DG1 y DG2 declarados en el SOD coinciden con los bytes
   recibidos.
4. El DSC encadena hasta una CSCA del `.pem` — construyendo la ruta a través de
   los eslabones si hace falta.

El paso 2 es el que se olvida y hace inútiles a los verificadores que sólo
comprueban la firma: sin él, un SOD con firma válida sobre unos atributos y un
eContent completamente distinto pasaría. Hay un test dedicado
(`test_rejects_a_substituted_econtent`).

No hay bandera de configuración que desactive ninguna. Un entorno sin cédulas
reales no obtiene una verificación falsa: obtiene un error.

### 2.3 El endpoint

```
POST /api/auth/cedula/verify
{
  "sod": "<base64 del EF.SOD>",
  "data_groups": { "1": "<base64 de DG1>", "2": "<base64 de DG2>" }
}
```

* **200** → `{ ok, identity_grant, identity_grant_expires_in, verification }`.
  El `identity_grant` es el mismo tipo de grant civil de un solo uso que emite
  ClaveÚnica: se canjea en `POST /api/auth/identity-credential`, que sí exige
  SIWE y liga la credencial a la wallet autenticada.
* **401** → `{ detail: { message, reasons: [...] } }`. `reasons` dice qué falló
  (hash de un DG, cadena, caducidad) para que la app pueda explicarlo.
* **503** → al servidor le faltan los certificados del Registro Civil. Es un
  fallo de despliegue, no del ciudadano.

`GET /api/auth/cedula/trust-store` expone contra qué anclas se valida
(subjects, huellas, caducidades). Público a propósito: cualquiera debe poder
comprobar en qué confía este servidor.

### 2.4 Configuración

```bash
IDENTITY_PROVIDER=clave-unica,cedula-nfc   # admite lista separada por comas
CSCA_TRUST_STORE_PATH=                     # vacío = app/certs/csca_chile.pem
```

`IDENTITY_PROVIDER` acepta ahora varios proveedores porque hay dos caminos
reales: ClaveÚnica en web, la cédula por NFC en el móvil. Un solo nombre sigue
significando lo mismo que antes. `/health/ready` bloquea el arranque en
producción si se declara `cedula-nfc` sin un trust store utilizable — declararlo
sin anclas dejaría un despliegue que acepta lecturas y las rechaza todas.

### 2.5 Fail-closed

* El simulador `POST /api/auth/nfc` responde **410 Gone** con la ruta correcta.
  Se eligió 410 y no 404 porque hay clientes desplegados llamando ahí.
* Los esquemas `NFCRequest`/`NFCResponse` se eliminaron: describían campos de
  una verificación que no ocurría.
* `POST /api/membership/mint` sigue bloqueado en producción. El camino real,
  `/mint-zk`, exige una prueba Groth16 contra una raíz de identidad aprobada
  on-chain; esa aprobación sólo ocurre dentro de `issue_credential`, que exige
  un grant. Con el simulador fuera, **los únicos emisores de grants son
  ClaveÚnica y la Autenticación Pasiva real**. Ése es el fail-closed pedido: no
  queda ninguna ruta de minteo que no pase por una firma del Registro Civil.

---

## 3. Lo que falta — para Codex (móvil)

El backend está listo y probado; **el móvil todavía no manda nada**. Hoy
`PassportReaderModule.kt` devuelve al puente el veredicto y los campos ya
interpretados, pero no los bytes. Sin los bytes, el servidor no puede verificar
— y con el veredicto solo, volveríamos exactamente al problema que esta fase
elimina.

### 3.1 Exponer los bytes crudos en el puente

En `PassportReaderModule.kt`, dentro del `Arguments.createMap()` que ya
construye la respuesta (junto a `identityVerified`, `data` y `verification`),
añadir:

```kotlin
putMap("raw", Arguments.createMap().apply {
    putString("sod", Base64.encodeToString(sodRaw, Base64.NO_WRAP))
    putMap("dataGroups", Arguments.createMap().apply {
        putString("1", Base64.encodeToString(dg1Raw, Base64.NO_WRAP))
        putString("2", Base64.encodeToString(dg2Raw, Base64.NO_WRAP))
    })
})
```

Las variables `sodRaw`, `dg1Raw` y `dg2Raw` ya existen en `readPassport()` —
son las que se pasan a `PassiveAuthenticator.verify()`. No hay que leer nada
nuevo del chip.

**Crítico:** tienen que ser los bytes **tal como se leyeron**, no un DG
reparseado y vuelto a serializar. El hash del SOD cubre el archivo completo con
su tag; volver a serializar produce bytes distintos y el paso 3 fallaría
siempre. Por eso el módulo ya los guarda en crudo — sólo hay que dejarlos
salir.

**Importante:** hay que devolver `raw` **aunque `identityVerified` sea
`false`**. Si el móvil sólo lo mandara cuando él da por buena la lectura,
volvería a ser el móvil quien decide, y un teléfono sin las CSCA en `assets`
—o con una versión vieja de la app— bloquearía lecturas que el servidor sí
puede validar.

### 3.2 Enviar la lectura al backend

En `nfcService.ts`, después de la lectura nativa:

```ts
const response = await fetch(`${API_URL}/api/auth/cedula/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        sod: native.raw.sod,
        data_groups: native.raw.dataGroups,
    }),
});
```

Y tratar el `identity_grant` de la respuesta como se trata hoy el de
ClaveÚnica: se canjea en `/api/auth/identity-credential` junto con el
`identity_commitment` que calcula el cliente.

El veredicto local (`identityVerified`) sigue sirviendo para la interfaz —
mostrar el error al instante, sin esperar a la red— pero **ya no decide nada**.
Si el servidor devuelve 401, la lectura no vale, diga lo que diga el teléfono.

### 3.3 Nada que cambiar en `assets/csca/`

Ya están las 5 anclas commiteadas. `loadTrustAnchors()` se endureció para que
sólo instale como `TrustAnchor` un certificado que verifique con su propia
clave (`isSelfSigned()`), por el mismo motivo del apartado 2.1: si alguien deja
caer ahí un link certificate, ya no se convierte en raíz.

### 3.4 Bloqueante previo — el CAN no cuadra entre JS y Kotlin

Encontrado de paso, y hay que resolverlo **antes** de poder probar nada de lo
anterior: hoy ninguna lectura llega a empezar.

| Sitio | Regla |
|---|---|
| `ScanScreen.tsx:82` y `nfcService.ts:490` | `/^[A-Z0-9]{9}$/` — 9 alfanuméricos |
| `PassportReaderModule.kt:124` | `length != 6 || !isLetterOrDigit()` — 6 exactos |

El commit `2f1a1e7` cambió la interfaz a 9 caracteres; el módulo nativo se
quedó en 6. Cualquier CAN que pase la validación de JS es rechazado por Kotlin
con `E_INVALID_CAN` antes de tocar el chip.

No lo he tocado: cuál es la longitud correcta del CAN de la cédula chilena es
una cuestión sobre el documento físico, no sobre el código, y elegir un número
a ojo aquí sería exactamente el tipo de suposición que esta fase evita. Quien
tenga una cédula delante decide, y los dos sitios tienen que decir lo mismo.

### 3.5 Formato de la respuesta 401

`detail` es un **objeto**, no una cadena:

```json
{ "detail": { "message": "...", "reasons": ["El contenido de DG1 no coincide con su hash firmado en el SOD."] } }
```

Conviene mostrar `reasons[0]`: distingue "cédula alterada" de "documento
caducado" de "CSCA desconocida", que para el usuario son problemas distintos.

---

## 4. Lo que sigue abierto

### 4.1 Replay — el hueco real

La Autenticación Pasiva demuestra que los datos los firmó Chile. **No demuestra
que el chip esté presente ahora.** Quien consiga los bytes de un SOD y sus DG
—leyendo la cédula ajena con el CAN, o interceptando un payload— puede
reenviarlos y obtener un grant para ese titular.

Lo que cierra el hueco es la **Autenticación Activa** o **Chip
Authentication**, donde el chip firma un desafío nuestro. No está implementada
ni en el móvil ni en el backend.

Lo que hoy acota el daño: el `subject_key` es el del titular del documento, no
el de quien envía. Un replay no crea una identidad nueva ni duplica ninguna —el
árbol de identidades es idempotente por sujeto—, así que el ataque se reduce a
suplantar a una persona concreta cuyo documento ya se leyó físicamente. Sigue
siendo grave.

### 4.2 El RUN en la MRZ — pendiente de confirmar con una cédula real

El `subject_key` se deriva del **RUN**, no del número de documento: el número
cambia en cada renovación y usarlo daría a la misma persona una identidad nueva
con cada cédula. El RUN se lee de `optionalData1` de la MRZ TD1
(`mrz.py::_parse_td1`, posiciones 15-30 de la línea 1).

**Esa posición no está confirmada contra una cédula chilena real.** Es la
ubicación documentada para el dato nacional en TD1 y lo que sugieren los campos
que el módulo nativo ya expone, pero nadie lo ha visto en un documento físico.

El sistema falla cerrado si la suposición es falsa: `normalize_run()` exige que
el valor tenga forma de RUN **y supere su dígito verificador módulo 11**. Si el
campo fuera otro, el dígito no cuadraría y la verificación se rechazaría con
"La MRZ del documento no expone un RUN reconocible" en vez de emitir
credenciales ligadas a un número que no identifica a nadie.

**Es la primera cosa a comprobar con una cédula real.** Si falla, el arreglo es
localizado: cambiar de qué posición sale `optional_data` en `_parse_td1`.

### 4.3 Revocación

El PKD publica CRLs en el archivo `-001`; no se consultan. Un DSC revocado pero
no expirado se aceptaría. Está en ROADMAP; fingir aquí una consulta que no se
hace sería peor que omitirla.

---

## 5. Cómo regenerar el trust store

```bash
python backend/scripts/extract_csca_from_ldif.py \
    "icao/icaopkd-002-complete-527 (1).ldif" \
    --country CL --subject-contains "Registro Civil" \
    --out backend/app/certs/csca_chile.pem \
    --anchors-dir mobile/android/app/src/main/assets/csca

# Ver qué hay sin escribir nada:
python backend/scripts/extract_csca_from_ldif.py <ldif> --country CL --dry-run
```

Dos tests de CI validan el archivo desplegado: que carga con anclas reales
(auto-firmadas, `C=CL`, Registro Civil) y que ningún eslabón queda huérfano. Si
alguien lo regenera con un filtro equivocado y deja dentro sólo link
certificates, la app arrancaría y rechazaría **todas** las cédulas — eso se
detecta en CI, no en producción.
