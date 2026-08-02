# Solicitud frontend → backend: emisión de credencial identity ZK

El frontend implementa el flujo wallet-bound del circuito
`MembershipEligibility(25)` y necesita un grant civil opaco de un solo uso más
un endpoint post-SIWE.

El proveedor de identidad **real** debe devolver `identity_grant` solo cuando
terminen satisfactoriamente todas las comprobaciones civiles. El grant debe
tener al menos 256 bits aleatorios, TTL corto, almacenarse como digest en el
servidor, no contener PII y no emitirse desde los simuladores actuales de
ClaveÚnica/NFC/liveness. El frontend lo conserva únicamente en memoria. La
respuesta del proveedor real debe incluir, como mínimo:

```json
{
  "ok": true,
  "identity_grant": "token opaco de un solo uso",
  "identity_grant_expires_at": "2026-08-01T12:34:56Z"
}
```

```http
POST /api/auth/identity-credential
Authorization: Bearer <sesión SIWE ligada a wallet_address>
Content-Type: application/json
```

Request:

```json
{
  "wallet_address": "0x...",
  "identity_commitment": "decimal BN254",
  "membership_scope": "decimal BN254",
  "membership_contract": "0x...",
  "chain_id": "11155111",
  "identity_grant": "token opaco de un solo uso"
}
```

El backend debe comprobar que la sesión SIWE pertenece exactamente a
`wallet_address`, consumir atómicamente el grant civil ligado al sujeto, validar
el contrato/red configurados y comprobar que `membership_scope` coincide con
`membershipScope()` on-chain. Debe insertar como máximo un commitment por
persona, construir la ruta Merkle de 25 niveles, publicar/aprobar la raíz en el
contrato antes de responder y devolver:

```json
{
  "ok": true,
  "identity": {
    "signature": "0x... EIP-191",
    "identity_root": "decimal BN254",
    "identity_commitment": "decimal BN254",
    "membership_scope": "decimal BN254",
    "wallet_address": "0x...",
    "path_elements": ["25 elementos decimales BN254"],
    "path_indices": ["25 bits 0/1"]
  }
}
```

La firma EIP-191 se calcula sobre este mensaje UTF-8 exacto (dirección en
minúsculas; enteros decimales canónicos):

```text
DAO Ciudadana Identity Credential v1
recipient:<wallet_address>
identityRoot:<identity_root>
scope:<membership_scope>
commitment:<identity_commitment>
```

El signer debe coincidir con `REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS`. El backend
no debe recibir nunca `identitySecret`, el claim firmado de vuelta, la ruta al
mintear ni datos civiles. El endpoint de relayer `POST /api/membership/mint-zk`
debe exigir otra vez una sesión SIWE para la misma `wallet_address` y recibirá
exclusivamente:

```json
{
  "wallet_address": "0x...",
  "pA": ["coordenada decimal", "coordenada decimal"],
  "pB": [["decimal", "decimal"], ["decimal", "decimal"]],
  "pC": ["coordenada decimal", "coordenada decimal"],
  "nullifier_hash": "0x... bytes32",
  "identity_root": "decimal BN254"
}
```

El relayer debe invocar exactamente:

```text
mintMembership(wallet_address, pA, pB, pC, nullifier_hash, identity_root)
```

y responder, después de confirmar y reconciliar la transacción:

```json
{
  "ok": true,
  "token_id": 123,
  "tx_hash": "0x..."
}
```

Tanto el intercambio de `identity_grant` como el mint deben ser idempotentes:
un timeout/retry con la misma wallet, grant y commitment no puede insertar otra
hoja ni enviar otra transacción. No registrar grant, firma, witness ni PII.

Importante para la migración actual: `backend/app/routers/auth.py` aplica
`require_non_production_identity_demo` a todo el router `/auth`. El endpoint
real `/auth/identity-credential` no puede heredar ese bloqueo de los simuladores;
debe quedar bajo su propia dependencia de producción y fallar cerrado si falta
el proveedor civil real.

## Seguimiento tras integrar backend `c9950d8`

El frontend quedó alineado con los tipos efectivamente implementados:
`identity_grant`, `chain_id` como string y coordenadas Groth16 decimales. Quedan
estos cambios exclusivamente backend antes de un E2E de producción:

1. No existe aún una ruta o callback de proveedor real que invoque
   `identity_grant.issue()` y entregue `identity_grant` al navegador. El
   servicio existe, pero solo lo ejercitan los tests; los simuladores no deben
   promoverse para resolverlo.
2. Un `mint_operations.status == "failed"` debe poder reintentarse de forma
   atómica. Actualmente el índice único hace que el retry termine como 409
   permanente.
3. Si el grant fue consumido y la primera aprobación de root falló, el retry
   debe volver a ejecutar/verificar `approve_identity_root` antes de devolver
   la credencial existente.
4. Tras confirmar `/membership/mint-zk`, reconciliar también la colección
   `members`; de otro modo `/membership/member/{wallet}` y las estadísticas no
   observan el SBT ZK recién emitido.

## TAREA 4 — contrato backend requerido por ERC-4337 y MACI

El frontend ya construye una Safe determinística, codifica una sola llamada a
`mintMembership`, valida la operación patrocinada completa y firma localmente
con el owner EIP-1193. No contiene una API key de Pimlico y falla cerrado si no
existe este contrato backend.

### ERC-4337 Safe + Pimlico

```http
GET /api/erc4337/config
Authorization: Bearer <SIWE>
```

Respuesta exacta mínima:

```json
{
  "enabled": true,
  "sponsorship_enabled": true,
  "account_type": "safe",
  "safe_version": "1.4.1",
  "safe_salt_nonce": "0",
  "safe_4337_module_address": "0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226",
  "use_multi_send_for_setup": false,
  "bundler_provider": "pimlico",
  "paymaster_provider": "pimlico",
  "paymaster": "0x...",
  "entry_point": "0x0000000071727De22E5E9d8BAf0edAc6f37da032",
  "entry_point_version": "0.7",
  "chain_id": "11155111",
  "chain_name": "Sepolia"
}
```

```http
POST /api/erc4337/prepare-mint
Authorization: Bearer <SIWE>
```

El request incluye `owner_address`, `safe_address`, `chain_id`, `entry_point`,
el perfil Safe, la prueba ZK pública y una UserOperation draft v0.7 con firma
stub. El backend debe:

1. comprobar que SIWE pertenece a `owner_address`;
2. recalcular la Safe con owner único, threshold 1, salt 0 y
   `useMultiSendForSetup=false`, usando exactamente el módulo Safe4337
   `0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226`;
3. decodificar `Safe4337Module.executeUserOpWithErrorString` y permitir una sola
   llamada, `operation=CALL`, valor cero, al SBT configurado;
4. decodificar esa llamada y exigir exactamente la misma wallet receptora,
   prueba, nullifier y root del request;
5. validar root/nullifier/no-membresía/idempotencia antes de gastar paymaster;
6. estimar y patrocinar con Pimlico sin cambiar sender, nonce, factory,
   factoryData ni callData.

Respuesta:

```json
{
  "ok": true,
  "operation_id": "id opaco idempotente por nullifier",
  "user_operation": {
    "sender": "0x...",
    "nonce": "0x...",
    "factory": "0x... opcional",
    "factoryData": "0x... opcional",
    "callData": "0x...",
    "callGasLimit": "0x...",
    "verificationGasLimit": "0x...",
    "preVerificationGas": "0x...",
    "maxFeePerGas": "0x...",
    "maxPriorityFeePerGas": "0x...",
    "paymaster": "0x...",
    "paymasterData": "0x...",
    "paymasterVerificationGasLimit": "0x...",
    "paymasterPostOpGasLimit": "0x...",
    "signature": "0x... firma stub"
  }
}
```

Después de que MetaMask firma todos esos campos:

```http
POST /api/erc4337/submit-mint
GET  /api/erc4337/operations/{user_operation_hash}
```

`submit-mint` debe recuperar `operation_id`, repetir las validaciones profundas,
aceptar únicamente la firma como campo modificado, enviar a Pimlico y persistir
`user_operation_hash`. Debe devolver siempre ese hash (incluso si ya conoce la
confirmación); el cliente calcula localmente el hash v0.7 y rechaza si difiere.
El endpoint de estado reconcilia receipt, `tx_hash`,
evento `MembershipMinted` y `token_id`. Un retry nunca crea otra UserOperation.
No usar `SAFE_OWNER_PRIVATE_KEY`: el servidor no es owner ni custodio.

### MACI 2.5

El frontend no usa `/api/governance/vote`: ese endpoint revela `for`, `against`
o `abstain`. `VotingBallot` sólo se habilita si `/api/maci/status` confirma a la
vez `key_registry`, `private_voting`, `coordinator_configured` y `tally_proof`.
Mantener esos flags en `false` hasta desplegar y probar el pipeline completo.

Corregir primero `POST /api/maci/keys`: además de estar en curva, cada coordenada
debe ser canónica `0 <= x,y < r`, el punto no puede ser `(0,1)` y
`subOrder * P` debe ser `(0,1)`. El endpoint actual acepta puntos de orden bajo.
El state tree MACI reserva el índice 0: `state_index` debe ser mayor que cero.

Tras registrar la llave pública del votante:

```http
GET /api/maci/proposals/{proposal_id}/poll
Authorization: Bearer <SIWE>
```

```json
{
  "protocol_version": "maci-v2.5.0",
  "proposal_id": "proposal-uuid",
  "poll_id": "7",
  "state_index": "4",
  "nonce": "1",
  "vote_weight": "1",
  "vote_options": { "for": "0", "against": "1", "abstain": "2" },
  "coordinator_contract": "0x... dirección del despliegue MACI confiable",
  "coordinator_public_key": { "x": "decimal", "y": "decimal" },
  "coordinator_key_hash": "0x... Poseidon(x,y) como bytes32",
  "chain_id": "11155111",
  "accepting_messages": true,
  "deadline": "fecha ISO-8601"
}
```

La llave coordinadora debe estar anclada on-chain. El despliegue se fija además
en `REACT_APP_MACI_COORDINATOR_ADDRESS`: el cliente rechaza si
`coordinator_contract` difiere, lee `coordinatorPubKeyX/Y` y `tallyVerifier`
desde esa dirección, exige que el verificador coincida con
`REACT_APP_MACI_TALLY_VERIFIER_ADDRESS` y que haya código en ambos contratos
antes de cifrar. También
recalcula `Poseidon(x,y)` y rechaza cualquier discrepancia. Los enteros
empaquetados deben cumplir `0 <= n < 2^50`, con `state_index` y `nonce`
positivos.

```http
POST /api/maci/polls/{poll_id}/messages
Content-Type: application/json
```

Este transporte no lleva el bearer SIWE. Recibe exclusivamente:

```json
{
  "protocol_version": "maci-v2.5.0",
  "proposal_id": "proposal-uuid",
  "poll_id": "7",
  "message": { "data": ["10 elementos decimales"] },
  "encryption_public_key": { "x": "decimal", "y": "decimal" },
  "coordinator_key_hash": "0x...",
  "idempotency_key": "UUID aleatorio"
}
```

No aceptar `wallet_address`, choice, comando, firma EdDSA, salt, shared key ni
llave privada en esa frontera. Antes de activar `private_voting`, definir una
prueba de elegibilidad anónima o relay que no vuelva a enlazar el ciphertext con
la sesión SIWE; separar axios elimina el identificador directo, pero no resuelve
por sí solo correlación de IP/tiempo. Persistir mensajes idempotentemente,
publicarlos en el contrato/poll real y no declarar un voto “contado” hasta
verificar el tally ZK. El contrato de publicación debe aceptar al relay anónimo
con una prueba de elegibilidad válida: una comprobación directa de
`signedUp[msg.sender]` es incompatible con este transporte porque `msg.sender`
será el relay, no la wallet inscrita.

El contrato/API definitivo debe exponer un anclaje verificable on-chain entre
`proposal_id`, `poll_id`, deadline y estado del poll. Hasta que el cliente pueda
contrastar ese vínculo (no sólo la llave global del coordinador), mantener
`private_voting=false`; una clave válida no prueba que el backend haya anunciado
el poll correcto.

La llave privada de votación del navegador hoy vive sólo durante la sesión. No
activar `private_voting` hasta definir recuperación o rotación de llave por poll
compatible con MACI (almacenamiento local cifrado o derivación wallet con dominio
separado); nunca persistir la llave privada en texto plano ni sobrescribir el
registro sin un `PCommand` de rotación válido.
