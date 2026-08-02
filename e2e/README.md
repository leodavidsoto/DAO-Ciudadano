# Suite E2E ZK + MACI

Esta suite levanta el frontend real en un puerto alternativo y recorre en
Chromium la emisión de una credencial ZK subsidiada y el envío de una papeleta
MACI. El backend, Pimlico, los contratos y la wallet EIP-1193 son fixtures
locales interceptados por Playwright: **el resultado no demuestra un despliegue,
una identidad civil, una ceremonia confiable ni una transacción real**.

El cliente sí carga los artefactos de desarrollo publicados por `frontend/`,
genera y verifica la prueba Groth16 localmente, deriva una Safe, firma la
UserOperation con una llave de prueba y cifra el comando MACI en el navegador.
La sesión se obtiene recorriendo challenge + firma EIP-191 + verify del fixture;
no se preinyecta un JWT.
Las aserciones comprueban que el grant/witness de identidad no cruza el límite
de minteo y que la urna anónima no recibe bearer, wallet ni preferencia plana.
Además, el runner reconstruye el formato `snarkjs` desde el calldata Solidity y
verifica la prueba independientemente; luego descifra el ciphertext con la
llave coordinadora determinista del fixture y valida el comando y su firma.

```bash
cd e2e
npm ci
npx playwright install chromium
npm test
```

El frontend usa `127.0.0.1:3005` por defecto. Para cambiarlo:

```bash
E2E_FRONTEND_PORT=3015 npm test
```
