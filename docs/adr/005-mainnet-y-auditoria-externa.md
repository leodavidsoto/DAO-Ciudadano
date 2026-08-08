# ADR-005: Despliegue en Mainnet y Auditoría Externa

**Estado:** Aceptado
**Fecha:** 2026-08-04

## Contexto

El contrato inteligente (`DAOCiudadanaSBT.sol`) actualmente opera en la red de pruebas Sepolia. Maneja las credenciales de membresía exclusivas (SBT) de los ciudadanos. La integridad y seguridad de este contrato son pilares fundamentales para el sistema democrático que se está construyendo. Desplegar este contrato en una red de producción (Mainnet) conlleva responsabilidades irreversibles.

## Decisiones

### 1. Requisito de Auditoría Externa Estricta
Bajo ninguna circunstancia se desplegará el contrato inteligente en una red principal sin una **auditoría de seguridad exhaustiva, externa e independiente**. 
- Esta auditoría debe ser realizada por una firma de seguridad blockchain reconocida.
- Se priorizará la revisión de vulnerabilidades de denegación de servicio (DoS), control de acceso, ataques de front-running en el minteo y mitigación de problemas relacionados a la actualización del contrato (si corresponde).
- El contrato desplegado en mainnet debe coincidir exactamente (por hash del bytecode) con el contrato auditado.

### 2. Selección de Red Mainnet
La DAO evaluará las redes EVM en base a los siguientes criterios:
1. **Costo de Transacciones (Gas):** Dado que se utilizará un Relayer/Paymaster para cubrir el gas (ADR-001), los costos deben ser manejables a escala masiva.
2. **Seguridad y Descentralización:** Priorizamos Rollups (Layer 2) respaldados por la red principal de Ethereum (Ej. Arbitrum, Optimism, Base) o sidechains probadas (Polygon).
3. **Soporte de Account Abstraction (ERC-4337):** La red debe tener bundlers y paymasters estables y bien soportados para posibilitar el esquema sin gas de los ciudadanos.

*Decisión Actual:* Polygon POS o Arbitrum One son los candidatos preferidos. La decisión final se tomará post-auditoría.

### 3. Procedimiento de Transición
Una vez elegida la red, se seguirá un manual de despliegue (`RUNBOOK`) que incluya:
- Despliegue de contrato desde una billetera fría / hardware.
- Transferencia inmediata de los roles `DEFAULT_ADMIN_ROLE` y demás privilegios a la DAO (Safe Multisigs designados).
- Renuncia de roles de la EOA deployer (Ejecutado inicialmente en `5.1-transfer-roles.js`).

## Consecuencias
- Queda prohibido el uso de tokens reales, elecciones vinculantes y la conexión de identidad real de producción al contrato de Sepolia.
- Retrasamos la salida a producción definitiva hasta conseguir financiamiento para la auditoría y formalización legal.
