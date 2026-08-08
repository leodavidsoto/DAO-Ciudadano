# Configuración de despliegue de contratos

Copia `.env.example` a `.env`; nunca versiones una llave privada ni entropía de
ceremonia.

## Redes y firma

```dotenv
SEPOLIA_RPC_URL=https://rpc.sepolia.org
POLYGON_RPC_URL=https://polygon-rpc.com
PRIVATE_KEY=llave_del_deployer_sin_prefijo_0x
ETHERSCAN_API_KEY=
POLYGONSCAN_API_KEY=
```

## Parámetros ZK obligatorios

Fuera de `hardhat`/`localhost`, `scripts/deploy.js` falla de forma cerrada si
falta cualquiera de estos valores:

```dotenv
SBT_ADMIN_ADDRESS=0xSafeOMultisig
ZK_VERIFIER_ADDRESS=0xVerifierAuditado
SBT_METADATA_URI=ipfs://dao-ciudadana/membership-v1
```

- `SBT_ADMIN_ADDRESS` recibe `ROOT_MANAGER_ROLE`, `PAUSER_ROLE`,
  `REVOKER_ROLE` y `DEFAULT_ADMIN_ROLE`.
- `ZK_VERIFIER_ADDRESS` debe ser el verifier desplegado desde el `.zkey` final
  de una ceremonia independiente. El script compara su bytecode con el
  `Verifier.sol` exacto del repositorio y nunca despliega automáticamente el
  verifier de desarrollo en una red pública. Además, bloquea el despliegue
  mientras `artifact-manifest.json` declare `productionReady: false`.
- `membershipScope` no se configura: el contrato lo deriva de versión,
  `chainId` y su propia dirección. El emisor y el cliente deben consultarlo
  on-chain antes de construir hojas o pruebas.
- `SBT_METADATA_URI` es común a todos los miembros y no puede contener PII.

Después del despliegue, el Safe con `ROOT_MANAGER_ROLE` debe aprobar la raíz
Merkle curada por el emisor antes de aceptar pruebas.
