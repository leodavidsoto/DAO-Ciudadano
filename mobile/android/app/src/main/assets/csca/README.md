# Anclas de confianza CSCA — VACÍO A PROPÓSITO

`PassportReaderModule.kt` carga desde esta carpeta los certificados de la
**Country Signing Certificate Authority** contra los que se valida la cadena
del Document Signer de la cédula (ADR-004, paso 3 de Passive Authentication).

Formatos aceptados: `.cer`, `.der`, `.pem`, `.crt` (X.509).

## Mientras esta carpeta no tenga el certificado de Chile

La autenticación pasiva **falla cerrada**: `identityVerified` es `false` y la
respuesta incluye el motivo

    "No hay ningún certificado CSCA instalado en la app: no se puede comprobar
     que la cédula la firmó el Registro Civil de Chile."

Es el comportamiento correcto, no un bug. Sin ancla de confianza lo único que
se puede afirmar es que *alguien* firmó esos datos — no que fuera el Registro
Civil. Un documento falsificado trae su propia cadena y verifica consigo mismo.

## Cómo conseguir el certificado

1. **ICAO PKD** (`https://pkddownloadsg.icao.int`) — master list oficial; Chile
   publica ahí su CSCA si participa del PKD.
2. **Registro Civil de Chile** — solicitud institucional directa.

Verifica el *fingerprint* SHA-256 por un canal distinto del de descarga antes
de commitearlo. Este archivo es el ancla de toda la verificación de identidad:
si se acepta uno equivocado, toda la cadena de confianza queda comprometida y
la app dirá "verificado" sobre documentos que no lo están.

**Nunca** uses el certificado que venga dentro de la propia tarjeta.

## Rotación

El riesgo está declarado en ADR-004: cuando el Registro Civil rote su llave,
una app publicada dejaría de validar cédulas nuevas. La mitigación propuesta
—un endpoint `/api/csca-masterlist` en el backend— todavía **no existe**.
