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

## Consecuencias y Siguientes Pasos
*   Se deben integrar librerías de ZK (`snarkjs`, `circomlib`) en el stack de contratos y frontend.
*   Se requiere desplegar infraestrucutra de relayer/paymaster.
*   El contrato `DAOCiudadanaSBT.sol` debe ser actualizado para verificar pruebas ZK en el minteo.
*   Los agentes (Codex y Claude) operarán de manera independiente basándose en los componentes técnicos definidos en sus respectivas *Skills*.
