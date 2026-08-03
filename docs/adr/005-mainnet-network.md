# ADR-005: Elección de Red Mainnet para Producción

## Estado
Propuesto

## Contexto
El contrato `DAOCiudadanaSBT` y la tesorería (`TREASURY_SAFE_ADDRESS`) deben ser desplegados en una red Mainnet para habilitar la Fase 5 (Producción). Debido a que hemos decidido utilizar un modelo de gas patrocinado por Paymaster (ERC-4337, ADR-001) para eliminar la fricción, necesitamos una red donde el costo del gas sea económicamente sostenible para la DAO a largo plazo, sin comprometer la seguridad descentralizada.

Opciones evaluadas:
1. **Ethereum Mainnet:** Seguridad máxima, pero costos de gas insostenibles ($5 - $30 USD por minteo o voto) que arruinarían la tesorería rápidamente.
2. **Polygon PoS:** Muy económico, gran soporte de ERC-4337 (Pimlico/Biconomy). Sin embargo, su seguridad y descentralización son menores al ser un sidechain con su propio set de validadores, en lugar de un verdadero Layer 2.
3. **Arbitrum One:** Rollup optimista de alta seguridad. Costos muy bajos (centavos) gracias a EIP-4844 (Blobs). Ecosistema robusto y soporte completo para Safe y AA.
4. **Optimism (OP Mainnet):** Similar a Arbitrum en seguridad y costos, con la ventaja organizativa del Optimism Collective y bienes públicos, lo que resuena con los valores cívicos de la DAO Ciudadana.
5. **Base:** Rollup soportado por Coinbase. Costos extremadamente bajos, pero aún con cierto control centralizado por parte del secuenciador.

## Decisión
Desplegaremos el contrato `DAOCiudadanaSBT`, los circuitos de ZK Tally y el Safe Multisig en **Arbitrum One** o **Optimism (OP Mainnet)** (a ratificar según alianzas, pero técnicamente ambas son válidas como Rollups L2 de Ethereum). 
Se recomienda comenzar con **Arbitrum One** debido a su probada liquidez, adopción generalizada de Account Abstraction (ERC-4337), y costos marginales por transacción post-Dencun (EIP-4844), lo que asegura que el patrocinio de gas no drene la tesorería.

## Consecuencias
- **A favor:** Gas sumamente barato; la DAO puede costear el minteo (SBT) y las transacciones MACI de decenas de miles de ciudadanos con un presupuesto mínimo en USD. El grado de seguridad hereda directamente de Ethereum L1.
- **En contra:** Los usuarios que quieran usar la tesorería u otras interacciones sin patrocinio necesitarán puentear (bridge) fondos hacia la L2.
- **Acciones siguientes:** Reflejar esta decisión configurando `HARDHAT_NETWORK=arbitrum` y aprovisionando los RPC públicos en `config.py`.
