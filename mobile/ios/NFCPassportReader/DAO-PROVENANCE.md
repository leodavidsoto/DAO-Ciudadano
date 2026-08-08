# Procedencia del fork iOS NFC

Este directorio parte de `AndyQ/NFCPassportReader` `2.3.3` (upstream
`6e37f1ab249fef82771da46d32707f2b94ed090f`) y conserva su licencia MIT en
`LICENSE`.

El código local difiere del tag para:

- fijar iOS 15 como mínimo;
- pasar explícitamente `paceKeyReference` desde el bridge para solicitar CAN
  (`0x02`);
- permitir que el consumidor prohíba el fallback BAC y cancele la sesión
  CoreNFC propietaria;
- evitar que CAN/MRZ, claves de sesión, nonces, tokens, shared secrets o APDU
  con contenido documental lleguen a OSLog.

La compatibilidad PACE-CAN no está validada por upstream ni por una prueba
física chilena en este repositorio. La interfaz exige `PACEStatus.success` y
falla cerrada si la librería cae a BAC. Antes de declarar Fase 4.2 completa se
deben registrar el dispositivo/iOS probados, el perfil de cédula, CAN correcto
y erróneo, y el resultado de autenticación pasiva contra el trust store
autorizado.

Los `masterList.pem` de los ejemplos upstream están excluidos por `.gitignore`
y no son anclas de confianza de esta aplicación. El release provisiona su PEM
desde un environment protegido y lo fija por SHA-256.
