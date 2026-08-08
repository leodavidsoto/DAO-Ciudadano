# Membresía ZK ligada a wallet

`verify_identity.circom` implementa la prueba Groth16 que autoriza el mint del
SBT sin publicar identidad civil, secreto ni ruta Merkle. Compila a **6.658
restricciones no lineales** y usa un árbol de 25 niveles (hasta 33.554.432
compromisos).

## Garantía criptográfica

El emisor valida unicidad civil fuera de cadena e inserta como máximo una hoja
por ciudadano:

```text
leaf = Poseidon(identitySecret, recipient, scope)
nullifierHash = Poseidon(identitySecret, scope)
```

La hoja ata la credencial a la wallet receptora. Copiar una prueba desde el
mempool no permite redirigir el SBT: como máximo, un tercero puede pagar el gas
para mintear el mismo token a la wallet prevista. El nullifier excluye la
wallet deliberadamente, por lo que la misma identidad no obtiene otro SBT al
cambiar de dirección.

Las señales públicas tienen este orden fijo, compartido por circuito,
`Verifier.sol` y `DAOCiudadanaSBT.sol`:

```text
[identityRoot, nullifierHash, recipient, scope]
```

El contrato construye ese array internamente, solo acepta raíces aprobadas y
consume cada nullifier para siempre, incluso si el SBT se revoca.

ZK no crea unicidad humana por sí solo. La resistencia Sybil depende de que el
emisor autentique a cada persona, emita una sola credencial y gobierne las
raíces con un Safe/multisig auditado.

## Entradas para generar una prueba

Entradas privadas:

- `identitySecret`: secreto de campo no cero generado en el dispositivo.
- `pathElements[25]`: hermanos de la ruta Merkle.
- `pathIndices[25]`: bits de posición de la hoja.

Entradas públicas:

- `identityRoot`: raíz autorizada por el contrato.
- `nullifierHash`: `Poseidon(identitySecret, scope)`.
- `recipient`: dirección EVM expresada como entero `uint160`.
- `scope`: dominio consultado desde `membershipScope()`; el contrato lo deriva
  de versión, `chainId` y su propia dirección.

El cliente genera `A/B/C` con:

```javascript
const { proof, publicSignals } = await snarkjs.groth16.fullProve(
  input,
  "circuits/build/verify_identity_js/verify_identity.wasm",
  "circuits/build/verify_identity_final.zkey"
);
```

Para Solidity, cada par Fq2 de `pi_b` debe adoptar el orden producido por
`snarkjs groth16 export soliditycalldata`; no se deben invertir coordenadas a
mano.

## Artefactos versionados

- `build/verify_identity_js/verify_identity.wasm`: generador de witness.
- `build/verify_identity_final.zkey`: proving key que coincide con el verifier.
- `build/verification_key.json`: verificación fuera de cadena.
- `../contracts/contracts/Verifier.sol`: verifier generado por `snarkjs`.
- `artifact-manifest.json`: hashes SHA-256, tamaños y frontera del protocolo.

Los `.ptau`, `.r1cs`, `.sym` y zkeys intermedios son regenerables y permanecen
ignorados.

## Reproducir y verificar

```bash
cd circuits
npm ci
npm run compile
npm run fixture
npm test
```

`npm run build` recompila, ejecuta un setup local, exporta los artefactos y
regenera el fixture. `circom2 --inspect`, `snarkjs powersoftau verify` y
`snarkjs zkey verify` forman parte del pipeline.

## Ceremonia y producción

El `.zkey` versionado permite integración end-to-end y **no es una ceremonia
de producción**: sus contribuciones ocurrieron en un solo host. Antes de un
despliegue público hay que ejecutar y documentar una ceremonia multipartita
con participantes independientes, auditar el circuito y reemplazar en el mismo
cambio el `.zkey`, `verification_key.json`, `Verifier.sol`, fixture y hashes.
El script de despliegue rechaza redes públicas mientras el manifiesto siga en
modo desarrollo, exige una dirección explícita y compara el hash del bytecode
desplegado con el `Verifier.sol` exacto del repositorio.
