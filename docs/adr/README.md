# Registro de decisiones de arquitectura (ADR)

Una decisión por fichero, numeración única, `NNN-slug.md`. Un ADR no se
reescribe cuando la realidad se aparta de él: se le añade una **enmienda**
fechada, para que quede el rastro de qué se decidió y qué se acabó haciendo.

| # | Decisión | Estado |
|---|---|---|
| [001](./001-arquitectura-vanguardia.md) | Arquitectura de vanguardia: ZK para identidad (D-2), Account Abstraction para el minteo (D-1), MACI para gobernanza (D-3) | Aprobado · **con Enmienda 1** |
| 002 | — *(no existe; nunca se escribió)* | — |
| [003](./003-revocacion.md) | Proceso de revocación de membresía | Aceptado |
| [004](./004-observabilidad.md) | Observabilidad, monitoreo y guardrails | Aceptado |
| [005](./005-mainnet-y-auditoria-externa.md) | Auditoría externa obligatoria antes de mainnet, y criterios de red | Aceptado |
| [006](./006-nfc-pace.md) | Implementación de NFC y PACE para la cédula chilena | Aceptado |
| [007](./007-nfc-sod.md) | Verificación criptográfica del SOD (CSCA y Document Signer) | Aceptado |
| [008](./008-red-l2-de-produccion.md) | Elección de red L2 para producción (Arbitrum / Optimism) | Propuesto |

## Historia de la numeración

Hasta el 08-08-2026 convivían dos series: `docs/ADR-00N-Nombre.md` y
`docs/adr/00N-slug.md`. Colisionaban en 003, 004 y 005 — dos documentos
distintos compartían número, y los dos «ADR-005» trataban temas contiguos
(uno exige auditoría externa, el otro elige la red). Se unificó todo aquí
renumerando la segunda serie a 006, 007 y 008; cada uno lleva una nota que
dice cuál era su número anterior. No se perdió ni se reescribió contenido.

## Enmienda vigente

**ADR-001, Enmienda 1 (08-08-2026).** El titular de la decisión D-1 nombra
ERC-4337, pero la app móvil mintea por el relayer (`/membership/mint-zk`),
porque ERC-4337 + Safe sigue sin credenciales de Pimlico ni Safe desplegada y
nunca ejecutó un envío. Respeta el cuerpo del ADR —que admite «un *Relayer* o
*Paymaster* de la DAO patrocina el gas»— y se aparta de su letra. Está escrito
dentro del propio ADR-001.
