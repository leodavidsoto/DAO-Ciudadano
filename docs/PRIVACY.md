# Política de Privacidad y Evaluación de Impacto (Ley 21.719)

**Fecha:** 2026-08-04

## Consentimiento y Privacidad
El proyecto "DAO Ciudadana" maneja información de ciudadanos chilenos. El pilar fundamental de nuestra arquitectura técnica es la minimización de datos personales y la privacidad por diseño.

### Ley 21.719 de Protección de Datos Personales
Para cumplir con los estándares de la nueva ley de protección de datos en Chile (Ley 21.719) y prevenir abusos:

1. **Minimización de Datos:** No almacenamos texto plano del RUT o el número de serie de la cédula en ninguna base de datos permanente o log de auditoría. Estos datos se procesan en memoria, se cifran de forma transitoria o se transforman en identificadores criptográficos (pruebas ZK / HMAC) que previenen la reconstrucción inversa del dato original.
2. **Consentimiento Versionado:** Cada ciudadano debe aprobar explícitamente y de manera granular el uso de su identidad civil para la emisión del Soulbound Token (SBT) de participación. 
   - El sistema almacena un registro inmutable del `consent_version` aceptado por la wallet durante el Onboarding.
   - Todo cambio a las políticas de privacidad requerirá una re-afirmación del consentimiento para continuar votando en nuevas elecciones.
3. **Cifrado en Reposo y Rotación:** Cualquier PII transitoria se cifra usando Fernet con un Pepper inyectado y rotado.
4. **Derecho al Olvido (Offboarding):** Los usuarios tienen derecho a solicitar que se desvincule y elimine permanentemente la conexión entre su identidad off-chain (registros cifrados en MongoDB) y su dirección en blockchain (SBT). El SBT se revoca y quema on-chain, y los datos cifrados locales se purgan según la política de retención (`retention.py`).

### Estatutos de la DAO
Se publicarán estatutos legibles en la aplicación web detallando las reglas democráticas, quorum, poder de veto de los Safes (si aplica) y responsabilidades de los representantes elegidos y el uso de los fondos de la Tesorería.

### Transparencia On-Chain
Los ciudadanos reconocen que, si bien su identidad civil está protegida mediante anonimato ZK o MACI, sus interacciones criptográficas con la DAO (Ej. delegaciones, si se publican en texto plano en la L2, o acciones desde su wallet a otros smart contracts) pueden ser observadas en la red pública, siendo su responsabilidad separar las wallets de DAO de sus finanzas personales.
