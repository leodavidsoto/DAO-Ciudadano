# ADR-001: Arquitectura de Vanguardia para DAO Ciudadana

**Fecha:** 1 de Agosto de 2026
**Estado:** Aprobado
**Autor:** Antigravity (Orquestador Principal)

## Contexto
El proyecto DAO Ciudadana se encontraba bloqueado por tres decisiones arquitectónicas clave (D-1, D-2 y D-3) respecto a la identidad on-chain, el minteo del SBT y la privacidad del voto. Las implementaciones tradicionales amenazaban con exponer datos personales (PII) o requerían que el usuario pagara comisiones de red (gas), limitando la adopción y la privacidad.

Se requiere un cambio de paradigma hacia un estándar de vanguardia que garantice anonimato, resistencia a la coerción, y nula barrera técnica para los ciudadanos de Chile.

## Decisiones Tomadas

### 1. Resolución de D-2 (Identidad On-Chain): Zero-Knowledge Proofs (zk-SNARKs)
En lugar de hashear el RUT (HMAC-SHA256) y guardarlo on-chain, implementaremos pruebas de conocimiento cero. 
*   **Diseño:** El servidor (u oráculo de identidad) emite un *claim* verificable tras la autenticación con ClaveÚnica/NFC. El cliente (frontend) genera una prueba ZK localmente usando `snarkjs` o un circuito de Semaphore, demostrando que posee un *claim* válido sin revelar de qué ciudadano proviene.
*   **On-chain (`identityHash`):** Se almacenará un `nullifier` de conocimiento cero. Esto evita el doble minteo sin exponer quién es el ciudadano.

### 2. Resolución de D-1 (Minteo del SBT): Account Abstraction (ERC-4337)
El minteo dejará de ser estrictamente custodial o requerir gas por parte del usuario.
*   **Diseño:** Utilizaremos Meta-Transacciones (ERC-2771) o Billeteras Inteligentes (ERC-4337). El usuario aprueba el minteo (y la prueba ZK) mediante una firma. Un *Relayer* o *Paymaster* de la DAO patrocina el gas.
*   **Impacto:** Fricción cero para el usuario. No necesita custodiar ETH.

### 3. Resolución de D-3 (Gobernanza): MACI + Democracia Líquida + SafeSnap
La gobernanza no será puramente on-chain por costos, ni puramente off-chain sin garantías.
*   **Voto Privado (MACI):** Minimal Anti-Collusion Infrastructure. Los votos se cifran y envían off-chain, y solo un coordinador puede desencriptarlos para probar el tally on-chain mediante zk-SNARKs. Esto impide la venta de votos y la coerción.
*   **Democracia Líquida:** Delegación transitiva de votos.
*   **Ejecución (SafeSnap / Reality.eth):** La tesorería estará en un Safe multisig. El oráculo de Reality.eth permitirá ejecutar las decisiones off-chain de manera on-chain y trustless.

---

## Enmienda 1 (08-08-2026) — el móvil mintea por relayer, no por ERC-4337

**Estado:** aprobado por el dueño del proyecto. No sustituye a la decisión 2, la acota.

El titular de la decisión 2 nombra ERC-4337. El camino ERC-4337 + Safe está
implementado en el frontend web (`prepare-mint`/`submit-mint`, no custodial),
pero **nunca ejecutó un envío**: no hay credenciales de Pimlico ni Safe
desplegada (`ROADMAP.md`, sección D-1). Exigirlo en el móvil implicaría
desplegar una Safe por ciudadano desde el teléfono y contratar el paymaster
antes de poder probar nada.

Por eso la app móvil mintea por `POST /membership/mint-zk`: el relayer de la
DAO envía la prueba y paga el gas.

**Esto respeta el cuerpo de la decisión 2**, que admite literalmente «un
*Relayer* o *Paymaster* de la DAO patrocina el gas», y mantiene las dos
propiedades que motivaron el ADR: no custodial (el secreto del ciudadano nunca
sale del dispositivo; la prueba Groth16 se genera en local) y fricción cero (el
ciudadano no necesita ETH). **Se aparta de su letra**, y por eso queda escrito
aquí en vez de como desviación silenciosa.

**Lo que esta enmienda no resuelve:**

- El gas de la DAO lo protege solo la sesión SIWE. El circuito liga `recipient`
  en la hoja y `mint_operations` da idempotencia por nullifier, así que nadie
  redirige un minteo ajeno; lo que queda expuesto es que un usuario autenticado
  queme gas con pruebas inválidas repetidas.
- La ceremonia de confianza sigue siendo de una sola parte
  (`circuits/artifact-manifest.json`: `productionReady: false`,
  `trustedSetup: "single-host-development-integration"`). Un minteo por este
  camino es válido para el piloto en testnet y **no debe llamarse producción**.

Cuando existan credenciales de Pimlico y una Safe desplegada, se reevalúa
volver a la letra del ADR.

---

## Consecuencias y Siguientes Pasos
*   Se deben integrar librerías de ZK (`snarkjs`, `circomlib`) en el stack de contratos y frontend.
*   Se requiere desplegar infraestrucutra de relayer/paymaster.
*   El contrato `DAOCiudadanaSBT.sol` debe ser actualizado para verificar pruebas ZK en el minteo.
*   Los agentes (Codex y Claude) operarán de manera independiente basándose en los componentes técnicos definidos en sus respectivas *Skills*.
