# ADR 0001 — Decisiones que bloquean la Fase 1

**Estado:** 🟡 Propuesto — pendiente de aprobación del dueño del proyecto
**Fecha:** 27 de julio de 2026
**Contexto:** [`../AUDIT.md`](../AUDIT.md) · [`../ROADMAP.md`](../ROADMAP.md)

---

## Por qué existe este documento

La Fase 1 (autenticación real y minteo on-chain) es lo único que convierte la afirmación central del producto en algo cierto. Hoy una persona completa el onboarding, ve confeti y un número de token, y no tiene nada: `totalSupply()` del contrato sigue en 0.

Esa fase está bloqueada por tres decisiones que no son preferencias técnicas. Definen quién custodia una llave capaz de acuñar membresías ciudadanas, qué queda publicado de forma permanente e irreversible sobre cada persona, y qué garantías puede afirmar la DAO sin mentir.

Cada sección plantea las opciones, recomienda una y **declara el riesgo que queda vivo** aunque se acepte la recomendación. Discrepar de la recomendación es una respuesta perfectamente válida; lo que no lo es es no decidir.

---

## D-1 · ¿Quién mintea el SBT?

### Opciones

| Opción | Cómo funciona | A favor | En contra |
|---|---|---|---|
| **A · Backend custodial** | El backend firma con una llave que tiene permiso de acuñación y llama a `mintMembership`. | Cero fricción: el ciudadano no necesita ETH ni entender Web3. Es lo que el contrato ya permite. | El backend custodia una llave con poder de acuñar. Si se filtra, se emiten membresías falsas hasta que alguien pause el contrato. |
| **B · Voucher firmado (EIP-712)** | El backend emite un vale firmado; la persona ejecuta la transacción y **paga su gas**. | El backend nunca custodia una llave con capacidad de gasto. | El ciudadano necesita ETH. En un proyecto cívico es una barrera de adopción que deja fuera justo a quien más debería participar. |
| **C · Meta-transacciones (relayer)** | La persona firma sin gas; un relayer ejecuta y paga. | Combina lo mejor de A y B. | Más piezas que construir y operar: relayer, protección contra su abuso, ERC-2771. |

### Recomendación: **A ahora, con controles, y camino a C**

El argumento decisivo no es técnico sino de propósito: esto es una plataforma cívica. Exigirle a un ciudadano que consiga criptomoneda para acreditar su identidad invierte la lógica del proyecto. La opción B queda descartada como punto de partida.

Entre A y C, A es lo que el contrato ya soporta y desbloquea la Fase 1 sin construir infraestructura nueva. Pero **A sin controles es inaceptable**, así que la recomendación incluye:

1. **Separar acuñar de administrar.** Migrar de `Ownable` a `AccessControl` con un `MINTER_ROLE` distinto del rol de administración. Una llave de acuñación filtrada podrá emitir membresías, pero **no** revocar, pausar ni transferir la propiedad del contrato.
2. **El administrador es un multisig (Safe), no una EOA.** Hoy el owner es una llave única — una "DAO" cuyo padrón depende de una sola persona.
3. **La llave de acuñación vive en un KMS gestionado**, nunca en variables de entorno ni en el repositorio.
4. **Límite de tasa y alertas** sobre el volumen de acuñación: un pico anómalo es la señal temprana de una llave comprometida.
5. El contrato ya impide re-acuñar la misma identidad (`_usedIdentityHashes`), lo que acota el daño de una filtración.

### Aprovechar que el redespliegue hoy es gratis

`totalSupply()` es **0**: no hay nada que migrar. Un redespliegue ahora no cuesta nada, y hacen falta **tres** cambios en el contrato que conviene juntar en uno solo:

- `AccessControl` con `MINTER_ROLE` (esta decisión)
- `identityHash` de `string` a `bytes32` (decisión D-2)
- el orden checks-effects-interactions ya corregido en el código pero **no** en el contrato desplegado (hallazgo N-2)

Si se pospone, cada uno de estos exigirá su propio redespliegue, y con miembros ya acuñados dejará de ser gratis.

### Riesgo que queda vivo

Aunque se apliquen los cinco controles, **el operador puede emitir membresías a voluntad**. La confianza en el padrón es confianza en quien opera el backend. Eso solo lo elimina la opción C con verificación independiente, y conviene decirlo en público en vez de dar a entender una descentralización que no existe todavía.

---

## D-2 · ¿Qué se escribe on-chain como `identityHash`?

### El problema actual

`generate_short_hash()` es `sha256(RUT)[:16]`, sin sal. El espacio de RUT chilenos válidos ronda los 30 millones: precomputarlos todos toma segundos. **Un hash de RUT sin sal no es anonimización.** Si ese valor llega a un registro público e inmutable, cualquiera puede revertirlo y obtener el padrón completo de ciudadanos, para siempre.

### Una restricción que descarta la opción más privada

El contrato usa `_usedIdentityHashes[identityHash]` para impedir que una misma persona obtenga dos membresías. Eso **exige que el hash sea determinista**: la misma identidad debe producir siempre el mismo valor.

Por lo tanto, una sal aleatoria por usuario —que sería lo más privado— **rompe la unicidad**: dos hashes distintos de la misma persona pasarían el control. No es una opción sin rediseñar esa garantía.

### Opciones viables

| Opción | Reversible por fuerza bruta | Preserva unicidad | Complejidad |
|---|---|---|---|
| `sha256(RUT)` (actual) | **Sí, en segundos** | Sí | — |
| **`HMAC-SHA256(RUT, pepper)`** con pepper en KMS | No sin el pepper | Sí | Baja |
| Prueba de conocimiento cero (Semaphore) | No | Sí, por otra vía | Alta |

### Recomendación: **HMAC-SHA256 con pepper en KMS**, 32 bytes completos, `bytes32` on-chain

Concretamente:

1. El pepper es un secreto de alto valor: vive en KMS, **nunca** en el repositorio, la base de datos ni los logs.
2. Usar los **32 bytes completos**, no 16 caracteres hexadecimales truncados.
3. Cambiar el tipo del contrato de `string` a `bytes32`: ahorra gas y elimina comparaciones de cadenas.
4. Purgar de la base los hashes generados con el esquema antiguo.

### Riesgo que queda vivo — léase con atención

**Si el pepper se filtra, todas las identidades ya acuñadas quedan reversibles de forma retroactiva y permanente.** No hay rotación posible: los valores on-chain son inmutables. Esto no es una objeción a la recomendación —es el mejor esquema simple disponible dada la restricción de determinismo— sino la consecuencia que hay que aceptar conscientemente.

Migrar más adelante a pruebas de conocimiento cero requerirá un contrato nuevo y no protegerá retroactivamente lo ya publicado.

**Antes de acuñar el primer token conviene una evaluación de impacto en protección de datos** (Ley 21.719). Publicar identificadores derivados de RUT en un registro público permanente es una decisión difícil de deshacer.

---

## D-3 · ¿La gobernanza es on-chain u off-chain?

### El problema actual

Propuestas, votos, delegaciones y tesorería viven íntegramente en MongoDB. **Quien opera el backend puede editar los resultados sin dejar rastro.** Eso no es una DAO todavía; es un formulario con estética de DAO.

### Opciones

| Opción | Garantía | Costo para el votante | Complejidad |
|---|---|---|---|
| **Off-chain firmado (EIP-712)** | Cada voto es un mensaje firmado; cualquiera puede reverificar el resultado sin confiar en el servidor. | Ninguno: firmar es gratis. | Media |
| On-chain completo (Governor + Safe) | Máxima. | Gas por cada voto. | Alta |

### Recomendación: **off-chain firmado, con tesorería en un Safe real**

El gas por voto es incompatible con la participación ciudadana masiva: convertiría el derecho a votar en algo que se paga. La firma EIP-712 elimina la debilidad que de verdad importa —que el operador fabrique votos— sin imponer costo.

Concretamente: tareas **3.2** (votos firmados) y **3.3** (nonce anti-replay), ambas ya en el roadmap y **desbloqueadas**. El campo `nonce` ya viaja en la petición y hoy se ignora.

La tesorería debe estar en un **Safe multisig real desde el principio**. El backend ya responde `configured: false` honestamente en vez de inventar saldos; conectarlo a un Safe cierra el hallazgo A-9 del todo.

### Riesgo que queda vivo

La firma impide **fabricar** votos, pero no impide **censurarlos**: el operador podría omitir un voto legítimo y nadie lo notaría. Mitigación recomendada: publicar periódicamente una raíz de Merkle de las papeletas on-chain, para que la omisión sea detectable. No es urgente para la Fase 3, pero conviene registrarlo antes de afirmar que la gobernanza es verificable.

---

## Qué se desbloquea al aprobar

| Decisión | Desbloquea |
|---|---|
| D-1 | 1.5 minteo real · 1.6 `MINTER_ROLE` · redespliegue del contrato (también N-2) |
| D-2 | 1.3 hash de identidad · 1.4 cifrado de PII · `bytes32` en el contrato |
| D-3 | 3.2 votos firmados · 3.3 anti-replay · 3.6 tesorería real |

**Ruta crítica:** D-1 → 1.1 autenticación → 1.5 minteo real. Hasta que 1.5 esté hecho, el producto no hace lo que dice hacer.

**Independiente de estas decisiones y con plazo ajeno al equipo:** iniciar hoy el trámite de acceso al sandbox de ClaveÚnica ante la División de Gobierno Digital. Bloquea toda la Fase 4 y no lo controla el equipo.

---

## Decisión

> Completar al aprobar. Registrar aquí las decisiones tomadas, quién las tomó y en qué fecha,
> y cambiar el estado del documento a **Aceptado**.

- **D-1:** _pendiente_
- **D-2:** _pendiente_
- **D-3:** _pendiente_
