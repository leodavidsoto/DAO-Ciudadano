# Anclas de confianza CSCA — Registro Civil de Chile

`PassportReaderModule.kt` carga desde esta carpeta los certificados de la
**Country Signing Certificate Authority** contra los que se valida la cadena
del Document Signer de la cédula (ADR-004, paso 3 de Passive Authentication).

Formatos aceptados: `.cer`, `.der`, `.pem`, `.crt` (X.509).

## Qué hay aquí

Las **cinco generaciones** de la CSCA del Servicio de Registro Civil e
Identificación, extraídas de la master list oficial del PKD de la ICAO
(`icaopkd-002-complete-527`) con
`backend/scripts/extract_csca_from_ldif.py`:

| Archivo | Vigencia | SHA-256 (16 primeros) |
|---|---|---|
| `csca_cl_01_4c2daca0fb8d73e1.pem` | 2013-08-01 → 2029-11-16 | `4c2daca0fb8d73e1` |
| `csca_cl_02_89f6143b835c2a41.pem` | 2016-08-01 → 2032-11-16 | `89f6143b835c2a41` |
| `csca_cl_03_bd10b0cf3addd12c.pem` | 2021-08-01 → 2037-11-16 | `bd10b0cf3addd12c` |
| `csca_cl_04_26539f4a222aec83.pem` | 2024-05-28 → 2039-06-13 | `26539f4a222aec83` |
| `csca_cl_05_b5dd74579cd7db82.pem` | 2026-05-05 → 2051-05-20 | `b5dd74579cd7db82` |

Sólo raíces **auto-firmadas**. Los *link certificates* de rotación que también
publica Chile NO están aquí: en esta carpeta todo se instala como
`TrustAnchor`, y un eslabón no es una raíz. Como cada generación tiene su
propia raíz auto-firmada, no hacen falta para encadenar ningún DSC.

Cada archivo se comprueba además en tiempo de carga: `isSelfSigned()` verifica
la firma con la propia clave del certificado. Desde la 4ª generación el
Registro Civil rota conservando el mismo DN, así que `subject == issuer` ya no
distingue una raíz de un eslabón — sólo la firma lo hace.

## Verificación cruzada

Estos certificados no salieron de ninguna tarjeta: vienen de las master lists
del PKD, donde cada país firma las CSCA de los demás. Cada uno de los cinco
aparece corroborado en varias master lists de administraciones distintas (de 2
a 11 según la generación; la 5ª es reciente y por eso tiene menos). El detalle
está en las cabeceras de `backend/app/certs/csca_chile.pem`.

**Nunca** uses el certificado que venga dentro de la propia tarjeta: un
documento falsificado trae su propia cadena y verificaría consigo mismo.

## Rotación

El riesgo sigue declarado en ADR-004: cuando el Registro Civil rote de nuevo,
una app ya publicada no tendrá la raíz nueva. Hoy hay margen —la 5ª generación
vale hasta 2051— pero la mitigación de fondo (servir la master list desde el
backend) sigue sin existir.

Para regenerar esta carpeta con una master list más nueva:

```bash
python backend/scripts/extract_csca_from_ldif.py \
    icao/icaopkd-002-complete-NNN.ldif \
    --country CL --subject-contains "Registro Civil" \
    --out backend/app/certs/csca_chile.pem \
    --anchors-dir mobile/android/app/src/main/assets/csca
```
