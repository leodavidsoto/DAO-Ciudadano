# ADR-003: Proceso de Revocación de Membresía

**Estado:** Aceptado
**Fecha:** 2026-08-04

## Contexto

El contrato inteligente de la membresía (`DAOCiudadanaSBT.sol`) implementa la capacidad técnica de revocar un SBT, reservada para el rol `REVOKER_ROLE` (ahora custodiado por un Safe Multisig) y condicionada a un *cooldown* de 3 días para mitigar ataques maliciosos o apresurados. 

Sin embargo, el proceso técnico no tiene valor si no está respaldado por un proceso de gobernanza transparente y verificado que dicte **cuándo** y **cómo** el multisig puede ejecutar la revocación.

## Decisiones

El proceso de revocación de una membresía se guiará estrictamente por las siguientes causales y pasos de ejecución:

### 1. Causales de Revocación
La revocación de un SBT solo podrá iniciarse bajo las siguientes circunstancias comprobadas:
- **Pérdida o Robo de Clave Privada:** El titular reporta (a través de un canal secundario autenticado, como ClaveÚnica o atestación física de Cédula de Identidad) que su wallet ha sido comprometida.
- **Suplantación de Identidad (Sybil):** Se demuestra criptográficamente que la cuenta en cuestión evadió los controles de unicidad o liveness (ej. uso de credenciales comprometidas o deepfakes en un proveedor no certificado).
- **Fallecimiento del Titular:** Presentación de certificado de defunción validado ante la DAO.
- **Solicitud Voluntaria (Offboarding):** El ciudadano decide renunciar a la membresía.

### 2. Proceso de Solicitud y Ejecución
- **Iniciación:** El proceso inicia mediante una Propuesta de Revocación formal on-chain/MACI, a menos que sea una Solicitud Voluntaria o Robo Reportado por el mismo titular.
- **Votación/Consenso Multisig:** El grupo con `REVOKER_ROLE` evaluará la evidencia. En caso de pérdida de clave, un oráculo de identidad (vinculado a ClaveÚnica) podrá atestar el reporte.
- **Periodo de Apelación:** Una vez que el `REVOKER_ROLE` firma la transacción de revocación, se activa el *cooldown* de 3 días inyectado en el smart contract. Durante este tiempo, la transacción permanece en pausa. Si la víctima de la revocación demuestra que es ilegítima, el multisig o el `DEFAULT_ADMIN_ROLE` puede anularla antes de que expire el cooldown.
- **Ejecución Final:** Expirado el plazo, la revocación surte efecto y el SBT es quemado, inhabilitando la participación del ciudadano de manera definitiva bajo esa dirección.

### 3. Recuperación
Un ciudadano revocado por pérdida de llave podrá volver a realizar el flujo de *Onboarding* con una nueva wallet, utilizando su misma identidad civil. El sistema debe garantizar que el antiguo SBT esté completamente invalidado antes de emitir uno nuevo a la misma identidad civil.

## Consecuencias
- Mantenemos un alto grado de rigor y protección contra la tiranía del administrador.
- Los 3 días de cooldown se justifican a nivel de gobernanza como ventana de apelación.
- Establecemos un estándar de protección al usuario en caso de hackeo de wallets, una fricción común en Web3.
