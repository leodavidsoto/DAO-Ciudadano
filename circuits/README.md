# Circuitos ZKP — identidad soberana

Estado: **andamiaje. No desplegar.** Este directorio existe para que la capa
ZKP tenga una forma concreta y discutible, no porque el flujo funcione.

## Qué hay implementado

`verify_identity.circom` calcula un **nullifier** = `Poseidon(documentIdHash, secret)`.

Eso resuelve la mitad *unicidad* del problema: la misma cédula produce siempre
el mismo nullifier, así que un contrato puede rechazar el segundo registro
(anti-Sybil), y el nullifier no revela el RUT.

`compile.sh` compila el circuito, corre el setup Groth16 y exporta
`contracts/contracts/Verifier.sol` con snarkjs.

## Qué falta (y por qué el circuito no sirve todavía)

El circuito **no verifica que los datos vengan del Registro Civil**. Hoy
cualquiera puede pasar un `documentIdHash` inventado y obtener una prueba
aritméticamente válida. Prueba unicidad de un dato no autenticado, que es
casi inútil por sí solo.

Para cerrarlo hacen falta dos cosas, en este orden:

### 1. Lectura autenticada de la cédula (bloqueante, va primero)

El circuito necesita como entrada privada el contenido real de **DG1** y la
firma de **EF.SOD**. Ambos solo se pueden leer tras establecer el canal seguro
BAC con el chip.

Estado en la app móvil:

- ✅ `mobile/src/services/bacCrypto.ts` — derivación de llaves BAC, Retail MAC
  y secure messaging, **verificado contra los vectores publicados de ICAO 9303
  Parte 11** (ver `__tests__/bacCrypto.test.ts`).
- ❌ Falta el intercambio de APDUs: autenticación mutua (`GET CHALLENGE` +
  `MUTUAL AUTHENTICATE`), y lectura de DG1/EF.SOD sobre el canal seguro.

Sin esto no hay nada que probar. Es el prerrequisito real, no el circuito.

### 2. Verificación de la firma dentro del circuito (caro)

Hay que verificar en el circuito que:

- el hash de DG1 aparece en EF.SOD, y
- EF.SOD está firmado por un Document Signer Certificate válido del
  Registro Civil de Chile.

Esto es lo pesado: RSA-2048 o ECDSA + SHA-256 dentro de un circuito
aritmético cuesta del orden de cientos de miles de restricciones. Es lo que
hacen proyectos como Anon Aadhaar o zkPassport, y es donde se va el 90 % del
esfuerzo.

Además hay una dependencia externa que no controlamos: **obtener y mantener
la lista de certificados públicos del Registro Civil chileno** (la Master List
del país). Sin esa clave pública no hay contra qué verificar.

## Costo de gas (por qué probablemente no vaya a mainnet)

Verificar Groth16 on-chain cuesta del orden de ~250k gas (tres emparejamientos
más la agregación de entradas públicas), y eso **no se optimiza desde
Solidity**: el verificador lo genera snarkjs. Sumando el mint del SBT, un
registro ronda las 300–400k de gas.

La palanca real no es micro-optimizar el contrato, es **desplegar en un L2**
(Base, Arbitrum, Optimism). Conviene decidirlo antes de la ceremonia de
confianza, porque cambiar de red después obliga a redesplegar.

Mídelo con `snarkjs r1cs info` (lo imprime `compile.sh`, paso 2): el número de
restricciones es el que manda.

## Conflicto con la arquitectura actual

Ojo, esto no es aditivo. Hoy el backend **es** la parte confiable: ve el RUT,
guarda el pepper, calcula `HMAC(pepper, doc_hash)`, tiene `MINTER_ROLE` y
mintea *por* el usuario (`backend/app/services/chain_service.py`).

El modelo ZKP invierte eso: el navegador prueba localmente, el backend queda
como simple relayer, y el usuario mintea con su propio `msg.sender`.

Adoptarlo implica **redesplegar el contrato** y reescribir la ruta de minteo.
La decisión D-1 de `docs/ROADMAP.md` ya lo advertía: *"Si se elige B o C hay
que redesplegar el contrato — decidirlo ahora evita hacerlo dos veces"*.

## Uso

```bash
cd circuits
npm install
npm run build     # requiere circom y snarkjs instalados globalmente
```

Los artefactos pesados (`.ptau`, `.zkey`, `.r1cs`, `.wasm`) **no van al
repositorio** — ver `.gitignore`. El `.wasm` y el `.zkey` finales sí hay que
empaquetarlos en el bundle del frontend para que el navegador pueda armar la
prueba; publícalos como assets del build, no como fuentes versionadas.

## Advertencia sobre la ceremonia de confianza

`compile.sh` hace una contribución de **una sola parte**, en tu máquina. Quien
haya corrido ese comando conoce el *toxic waste* y **puede fabricar pruebas
falsas**. Sirve para desarrollo y nada más. Producción exige una ceremonia
multi-parte con participantes independientes.
