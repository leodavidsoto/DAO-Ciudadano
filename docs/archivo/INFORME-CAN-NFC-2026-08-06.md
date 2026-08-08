# Informe — validación del CAN en la lectura NFC y estado de la app

**Fecha:** 6 de agosto de 2026
**Autor:** Claude (dominio backend + contratos, según [`CLAUDE_SKILLS.md`](../CLAUDE_SKILLS.md))
**Origen:** capturas de pantalla de la app en un dispositivo físico aportadas por el dueño del proyecto
**Ramas involucradas:** análisis sobre `origin/codex/produccion-ci`; este informe se escribe en `claude/digito-9-caracteres-ty11yf`

---

## Alcance — qué se hizo y qué no

**Se hizo:** lectura del código de lectura NFC/PACE en las cuatro capas donde vive
(Kotlin nativo, Swift nativo, servicio TypeScript y pantalla React Native), lectura
completa de los 26 documentos `.md` del proyecto en `codex/produccion-ci`, y
verificación determinista del comportamiento de las expresiones regulares de
validación con Node.

**No se hizo:** no se compiló la app, no se ejecutó la suite Jest de `mobile/`
(el árbol no tiene `node_modules` y las dependencias de React Native son pesadas),
no se leyó una cédula física y **no se cambió ni una línea de código**. Todo lo que
sigue son hallazgos de lectura y de razonamiento verificable, no resultados de
ejecución, salvo donde se indica explícitamente lo contrario.

**No se tocó código a propósito.** `CLAUDE_SKILLS.md` establece que `mobile/` y
`frontend/` son dominio de Codex. Los dos hallazgos de este informe caen enteros
en `mobile/`. La decisión de quién aplica el arreglo queda en manos del dueño del
proyecto (ver «Decisión pendiente» al final).

---

## Hallazgo 1 — el CAN se valida contra 6 caracteres; la cédula pide 9

### Evidencia

Tres capturas consecutivas del mismo dispositivo muestran la progresión:

| Hora | Mensaje en pantalla | Lectura |
|---|---|---|
| 6:42 | `NoClassDefFoundError: Lorg/bouncycastle/asn1/eac/EACObjectIdentifiers;` | El build no resolvía BouncyCastle |
| 6:50 | `NoClassDefFoundError: org.jmrtd.lds.SecurityInfo` | El build no resolvía JMRTD |
| 6:52 | `El CAN debe contener exactamente los 6 caracteres impresos en la cédula.` | **El binario ya arranca**; ahora falla la validación de entrada |

La tercera captura es la importante: el módulo nativo carga correctamente y el
flujo llega hasta la validación del CAN. El dueño del proyecto reporta que el
número impreso en su cédula es de **9 caracteres**, no de 6.

Esto es exactamente la incertidumbre que el propio proyecto tenía registrada como
abierta en [`AUDIT.md`](./AUDIT.md), hallazgo **P-82**:

> «El soporte CAN sigue sin validación upstream ni prueba física chilena […]
> cerrar el hallazgo requiere vectores o cédula física, CAN correcto/erróneo y
> evidencia reproducible.»

La captura de las 6:52 es esa prueba física, y contradice el supuesto de 6.

### Dónde está el 6 hardcodeado

La constante está repetida en **cinco lugares** de dos lenguajes distintos, sin
una única fuente de verdad. Cualquier corrección tiene que tocarlos todos o la
app quedará inconsistente entre plataformas:

| Archivo | Línea | Qué contiene |
|---|---:|---|
| `mobile/android/app/src/main/java/com/daociudadanaapp/PassportReaderModule.kt` | 124 | `normalizedCan.length != 6 \|\| !normalizedCan.all { it.isLetterOrDigit() }` |
| `mobile/ios/DAOCiudadanaApp/PassportReader.swift` | 40 | `normalizedCan.utf8.count == 6` **y solo dígitos ASCII** |
| `mobile/src/screens/ScanScreen.tsx` | 82 | `/^[A-Z0-9]{6}$/` |
| `mobile/src/screens/ScanScreen.tsx` | 136, 142, 144 | `placeholder="Ej: 123456"`, `maxLength={6}`, texto de ayuda «los 6 caracteres» |
| `mobile/src/services/nfcService.ts` | 490 | `/^[A-Z0-9]{6}$/i` |

`maxLength={6}` (ScanScreen.tsx:142) merece atención aparte: **impide físicamente
tipear un séptimo carácter**. Aunque se relajaran las validaciones, el campo
seguiría truncando la entrada y el usuario no tendría forma de introducir un CAN
de 9. Es el más fácil de pasar por alto y el que bloquea de verdad.

**Android e iOS además divergen entre sí:** Android acepta alfanuméricos desde el
commit `bc179e3`; iOS sigue exigiendo 6 **dígitos** ASCII. Un mismo CAN con letras
sería aceptado en Android y rechazado en iOS.

### Por qué el arreglo es acotado y seguro

Se revisó qué recibe el valor una vez pasa la validación:

- **Android** — `PassportReaderModule.kt:259`: `PACEKeySpec.createCANKey(can)`
- **iOS** — `PassportReader.swift:88-90`: `reader.readPassport(mrzKey: normalizedCan, …, paceKeyReference: 0x02)`

Ninguna de las dos librerías (JMRTD, NFCPassportReader) impone una longitud fija:
reciben el string tal cual. **El «6» no viene del estándar ni de las dependencias,
lo introdujo esta app.** El origen más probable es el CAN alemán de BSI TR-03110,
que sí es de 6 dígitos, adoptado por analogía y nunca contrastado contra una cédula
chilena — que es literalmente lo que P-82 dejó anotado como pendiente.

Corregirlo es cambiar una constante de longitud en cinco sitios. **No toca la
criptografía, ni PACE, ni la autenticación pasiva.**

### Lo que falta confirmar antes de aplicar el cambio

No está confirmado si el número de 9 caracteres es:

- **(a)** el CAN impreso en el frente de la cédula, junto al ícono NFC, o
- **(b)** el número de documento.

La distinción importa porque son entradas de protocolos distintos: el CAN alimenta
PACE (el camino que esta pantalla ejecuta), mientras que el número de documento
alimenta la MRZ y por tanto BAC (`bacCrypto.ts`, camino separado que este flujo no
usa). Si resultara ser (b), el arreglo no es cambiar el largo del CAN sino cambiar
qué se le pide al usuario, que es un cambio bastante mayor.

**Recomendación:** confirmar con la cédula a la vista qué rótulo acompaña al número
de 9 caracteres antes de tocar nada.

---

## Hallazgo 2 — un test de `mobile/` quedó obsoleto y debe estar fallando

Detectado al verificar los números de línea del hallazgo anterior. Es independiente
de él y probablemente ya esté rompiendo CI.

`mobile/src/services/__tests__/nfcService.test.ts:138` contiene:

```ts
it('validates the CAN before invoking the native module', async () => {
    …
    const result = await nfcService.readChileanIDPACE('12A456');
    expect(result).toEqual(expect.objectContaining({
        status: 'failed',
        errorCode: 'E_INVALID_CAN',
    }));
    expect(startPACESession).not.toHaveBeenCalled();
});
```

El test usa `'12A456'` como ejemplo de CAN **inválido** — válido cuando la
validación era `/^\d{6}$/` y las letras se rechazaban.

El commit `bc179e3` («permitir CAN alfanumérico y evitar cierres inesperados en
PACE», 04-08-2026) relajó la validación a `/^[A-Z0-9]{6}$/i` en `nfcService.ts:490`
y a `it.isLetterOrDigit()` en el Kotlin, pero **no actualizó el test**: ese commit
tocó únicamente `PassportReaderModule.kt`, `ScanScreen.tsx` y `nfcService.ts`.

Verificación ejecutada (Node, sobre el HEAD de `codex/produccion-ci`):

```text
input del test: 12A456
  nfcService acepta?    true
  ScanScreen acepta?    true
  => el test espera E_INVALID_CAN; al aceptarlo, el test FALLA
```

`'12A456'` ahora pasa la validación, así que `readChileanIDPACE` llama al módulo
nativo en vez de rechazar, y fallan las dos aserciones.

**Salvedad honesta:** se verificó el comportamiento de las expresiones regulares de
forma determinista, **no se ejecutó la suite Jest completa** (sin `node_modules`).
La conclusión se sigue del comportamiento de las regex, que no es ambiguo, pero
conviene confirmarla con `npm test` en `mobile/`.

**Por qué importa más allá del test:** `ROADMAP.md` (2.9) declara el gate estático
de mobile como completado — «Una regresión móvil bloquea el PR antes del build
nativo» — y `mobile/README.md` afirma que la app «pasa TypeScript, 43 tests, lint».
Si este test está rojo, esas dos afirmaciones no describen el estado real. Es
precisamente el patrón que `AGENTS.md` regla 3 prohíbe: dar por completo algo cuyo
camino real no se ejecutó.

---

## Estado general de la app

Contexto para dimensionar los hallazgos anteriores. Todo esto sale de leer los
`.md` del proyecto y contrastarlos con el código en `codex/produccion-ci`.

### Cambio de arquitectura

`codex/produccion-ci` va **69 commits por delante de `main`** e implementa
[`ADR-001`](./ADR-001-VANGUARD-ARCHITECTURE.md), que resuelve las tres decisiones
que en `main` seguían abiertas:

| Decisión | Resolución en ADR-001 |
|---|---|
| **D-1** ¿quién mintea el SBT? | ERC-4337 no custodial: el ciudadano firma con su Safe, un paymaster paga el gas |
| **D-2** ¿qué va on-chain como identidad? | zk-SNARK con nullifier (`MembershipEligibility(25)`), no hash de RUT |
| **D-3** ¿gobernanza on-chain u off-chain? | MACI (voto cifrado anti-coerción) + Safe/Reality.eth |

### Lo que funciona de verdad

- **Backend:** 331 tests, PII cifrada (Fernet + índices HMAC) en altas nuevas,
  sesión SIWE en cookie `HttpOnly` + CSRF de doble envío, tesorería real leída de
  un Safe (nativo + ERC-20 + precios CoinGecko), papeletas EIP-712 reverificables
  por terceros con endpoint público de auditoría.
- **Contratos:** `AccessControl` con roles separados ya transferidos a Safes en
  Sepolia (la EOA renunció a sus privilegios), soulbound, revocación con cooldown
  de 3 días, 31 tests.
- **Android/NFC:** el módulo nativo compila y **ejecuta PACE real contra un chip
  real**. Las capturas del dueño lo demuestran: ya superó los dos
  `NoClassDefFoundError` y llega hasta la validación de entrada. Esto no es un mock.
- **CI:** 6 jobs, Actions fijadas por SHA, `pip-audit --strict`, slither, E2E
  Playwright, Dependabot en cinco ecosistemas.

### Lo que sigue bloqueado

| Área | Estado real |
|---|---|
| **Minteo en producción** | Cerrado. Sin proveedor civil real no hay `identity_grant`; falla cerrado a propósito |
| **Voto privado (MACI)** | `private_voting: false`. Cuatro fallos de protocolo abiertos: replay entre polls, nonce no comprometido en el circuito, hojas duplicadas en el tally, tally no enlazado a `processMessages` |
| **ERC-4337** | Nunca se ejecutó un envío real: sin credenciales de Pimlico ni Safe desplegada |
| **NFC — verificación** | Aunque se arregle el CAN, **sin el certificado CSCA de Chile la identidad no se puede verificar**. La app falla cerrada a propósito (P-80) |
| **NFC — iOS** | Cableado pero nunca ejecutado sobre hardware; el fork con soporte CAN no está validado upstream (P-82) |
| **Contrato desplegado** | La dirección histórica de Sepolia usa otra ABI y es incompatible. No existe despliegue del contrato actual. `totalSupply()` = 0 |
| **Datos legacy** | `users` sin migrar ni cifrar. Bloqueante antes de cualquier uso real |
| **Infraestructura** | Render free tier declarado no apto para producción en [`ADR-004`](./ADR-004-Observability.md) |

### Dependencias externas — el cuello de botella real

Dos piezas que **nadie del equipo controla** bloquean la identidad de punta a punta:

1. **El certificado CSCA de Chile** (Registro Civil o ICAO PKD). Sin él, la
   autenticación pasiva no tiene ancla de confianza y `identityVerified` es
   siempre `false`. Está correctamente documentado en
   `mobile/android/app/src/main/assets/csca/README.md`, que además advierte:
   nunca usar el certificado que venga dentro de la propia tarjeta.
2. **El acceso al sandbox de ClaveÚnica** (División de Gobierno Digital). El
   código OIDC con PKCE está implementado y el binding de navegador cerrado
   (P-78), pero falta el trámite administrativo.

Arreglar el CAN es necesario para que la lectura funcione, pero **no desbloquea la
verificación de identidad** por sí solo.

---

## 🔴 Sin relación con lo anterior — acción pendiente del dueño

[`SECURITY_RUNBOOK.md`](./SECURITY_RUNBOOK.md) documenta un **P0 abierto**: el
repositorio es público y tres commits históricos (`8d66b97`, `6202a9f`, `9977a2f`)
contienen un `backend/.env` con una `EMERGENT_LLM_KEY` real.

La llave **debe considerarse comprometida** y rotarse, aunque ya no exista en
`HEAD`. Es una acción del dueño del proyecto, no de un agente, y no depende de
ninguna otra tarea de este informe. Borrar los blobs del historial no sustituye a
revocarla: revocar va primero.

---

## Decisión pendiente

El arreglo del CAN cae íntegramente en `mobile/`, que `CLAUDE_SKILLS.md` asigna a
Codex. Hay tres caminos y la elección es del dueño del proyecto:

1. **Que lo aplique Codex** — respeta la separación de dominios. Requiere pasarle
   el hallazgo, idealmente vía `REQUEST_TO_CODEX.md`.
2. **Que lo aplique Claude** — rompe la convención, pero se trata de una constante
   de validación en cinco sitios, no de arquitectura.
3. **Esperar** a confirmar si el número de 9 caracteres es el CAN o el número de
   documento (ver «Lo que falta confirmar»). Si fuera lo segundo, el arreglo es
   distinto y mayor.

En cualquier caso, el arreglo debe incluir: los cinco sitios listados, el
`maxLength` del `TextInput`, la alineación entre Android e iOS (alfanumérico vs.
solo dígitos) y la actualización del test obsoleto del Hallazgo 2.
