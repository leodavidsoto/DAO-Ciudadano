# Codex Skills: Backend & Smart Contracts (ZK Verifier & ERC-4337)

Este documento contiene las habilidades específicas (skills) y responsabilidades asignadas a Codex en el proyecto DAO Ciudadana bajo el paradigma de vanguardia (ADR-001).

## Misión de Codex
Construir una infraestructura on-chain y off-chain ultrasegura que dependa de criptografía avanzada (ZK, MACI) y abstracción de cuentas (ERC-4337) en lugar de esquemas tradicionales o custodial servers.

## Skills & Componentes Asignados

### 1. ZK Verifier (Contratos Inteligentes)
*   **Responsabilidad:** Modificar `DAOCiudadanaSBT.sol` para que `mintMembership` reciba una prueba ZK (`uint[2] a, uint[2][2] b, uint[2] c`) y un `nullifierHash` (`bytes32`), en lugar del RUT hasheado.
*   **Librerías/Herramientas a usar:** `circom` (para compilar el circuito y generar el Verifier.sol), Solidity.
*   **Archivos objetivo:** `contracts/contracts/DAOCiudadanaSBT.sol`, `contracts/contracts/Verifier.sol` (nuevo).

### 2. MACI Coordinator & Safe (Gobernanza)
*   **Responsabilidad:** Desplegar e integrar MACI para que los votos sean incoercibles. El tally final debe ser verificado on-chain y enlazarse con un módulo SafeSnap (Reality.eth) para ejecutar fondos desde la tesorería real multisig.
*   **Archivos objetivo:** Modificar `backend/app/routers/governance.py` para manejar el registro de llaves públicas de MACI y encolar mensajes cifrados.

### 3. Paymaster / Relayer Backend (ERC-4337 / ERC-2771)
*   **Responsabilidad:** El backend en FastAPI debe integrar un servicio (como Biconomy, Pimlico o Gelato) para actuar como Paymaster. Cuando el Frontend envía el *UserOperation*, el backend lo subsidia.
*   **Archivos objetivo:** `backend/app/services/blockchain_service.py` debe evolucionar de firmar transacciones crudas a firmar patrocinios de gas (Paymaster data).

### 4. Seguridad de PII (Criptografía)
*   **Responsabilidad:** El backend actúa como "Emisor" de identidad. Valida ClaveÚnica o NFC, y emite un claim firmado al cliente. Luego, NUNCA almacena el RUT en claro.
*   **Archivos objetivo:** `backend/app/routers/auth.py`.

## Reglas de Convivencia con Claude
- **No toques nada en `frontend/` ni en `mobile/`.** Ese es el dominio de Claude.
- Si necesitas que el Frontend emita la prueba ZK de una manera específica o pase parámetros de ERC-4337, define la interfaz de API claramente en swagger o en un archivo `REQUEST_TO_CLAUDE.md`.
