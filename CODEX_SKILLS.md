# Codex Skills: Frontend & Mobile (ZK & UI)

Este documento contiene las habilidades específicas (skills) y responsabilidades asignadas a Codex en el proyecto DAO Ciudadana bajo el paradigma de vanguardia (ADR-001).

## Misión de Codex
Transformar la interfaz web (`frontend/`) y móvil (`mobile/`) en una DApp inmersiva, de estilo cyberpunk-estatal, que maneje Zero-Knowledge Proofs localmente en el navegador/dispositivo.

## Skills & Componentes Asignados

### 1. ZK-Client (Zero Knowledge en el Navegador)
*   **Responsabilidad:** Debes implementar la generación de pruebas ZK en el cliente usando `snarkjs`. El backend enviará un claim firmado (la identidad validada), pero el cliente NUNCA enviará ese claim de vuelta al mintear. En su lugar, el cliente computa la prueba ZK localmente.
*   **Librerías a usar:** `snarkjs`, ethers.js.
*   **Archivos objetivo:** Modificar `frontend/src/context/OnboardingContext.jsx` y crear `frontend/src/lib/zk.js`.

### 2. MACI Integrator (Voto Privado)
*   **Responsabilidad:** Para la votación de gobernanza (Fase 3), debes integrar el cliente de MACI. Al votar, el usuario no envía su voto en texto plano ni como un EIP-712 simple, sino cifrado con la clave pública del coordinador de MACI.
*   **Archivos objetivo:** Componentes dentro de `frontend/src/components/governance/`.

### 3. Account Abstraction UX (ERC-4337)
*   **Responsabilidad:** Ocultar completamente la complejidad de tener "gas". La interfaz debe conectarse a través de un Bundler/Paymaster.
*   **Flujo:** En lugar de "Firmar Transacción", el botón debe decir "Autorizar Emisión (Subsidiada por el Estado)".

### 4. Estilo Cyberpunk Estatal
*   **Responsabilidad:** Mantener y extender `styles/premium.css` y `styles/civic.css`. Evita los diseños genéricos. La DApp debe verse como una terminal ultra-segura del futuro, con micro-animaciones (framer-motion o CSS puro). NUNCA uses placeholders ni datos falsos (Regla de AGENTS.md).

## Reglas de Convivencia con Claude
- **No toques nada en `backend/` ni en `contracts/`.** Ese es el dominio de Claude.
- Si necesitas un endpoint específico de backend para obtener las llaves públicas de MACI o los parámetros del circuito ZK, escribe tus requerimientos en un archivo `REQUEST_TO_CLAUDE.md`.
