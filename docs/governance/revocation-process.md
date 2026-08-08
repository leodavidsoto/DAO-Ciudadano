# Proceso de Revocación de Membresía SBT

Este documento detalla el procedimiento formal, las causales y el mecanismo de apelación para la revocación de un SBT (Soulbound Token) de la DAO Ciudadana, en cumplimiento con la Fase 5.2 del Roadmap.

## Principios Fundamentales
1. **La revocación es el último recurso.** Solo se ejecuta cuando hay evidencia criptográfica o legal innegable de fraude o pérdida irremediable de llaves.
2. **Ningún individuo tiene poder unilateral.** Solo el contrato Safe Multisig (gobernado descentralizadamente) ostenta el `REVOKER_ROLE`.
3. **El cooldown garantiza transparencia.** Toda revocación iniciada tiene un retraso (cooldown) de 3 días antes de hacerse efectiva on-chain, tiempo en el que la comunidad y el afectado son notificados.

## Causales de Revocación Válidas
Para que una propuesta de revocación sea admitida, debe fundarse en una de las siguientes causales:

1. **Compromiso de Llave Privada:** El ciudadano notifica formalmente que su wallet ha sido vulnerada y solicita la revocación para proteger su identidad (y emitir una nueva posteriormente).
2. **Fraude en el Alta (Sybil Attack):** Evidencia técnica de que una misma persona física vulneró el proveedor de identidad o liveness para obtener múltiples SBTs.
3. **Fallecimiento del Titular:** Presentación de certificado de defunción validable mediante el Registro Civil, asegurando que la membresía no pueda ser operada por terceros.

*Nota: Emitir un voto impopular, pensar distinto a la mayoría o tener inactividad prolongada **NUNCA** son causales válidas de revocación.*

## Flujo de Ejecución

1. **Levantamiento de la Petición:** Un miembro o el propio afectado sube una propuesta formal de revocación adjuntando la evidencia (ej. transacción de robo, reporte de vulnerabilidad, etc.).
2. **Validación del Multisig:** El comité o los firmantes del Safe verifican que la evidencia concuerda con las causales válidas.
3. **Trigger On-Chain (`revokeMembership`):** Si hay quórum en el Safe, se llama a la función en el contrato. El SBT entra en estado de *Cooldown* por 72 horas.
4. **Ventana de Apelación:** Durante estas 72 horas, la revocación puede ser cancelada (`cancelRevocation`) si se demuestra que la propuesta era infundada o producto de un error.
5. **Efectivización:** Transcurrido el tiempo, la membresía queda revocada permanentemente. El ciudadano pierde su poder de voto, pero su historial MACI preserva su privacidad.
