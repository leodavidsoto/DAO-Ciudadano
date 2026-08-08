package com.daociudadanaapp

import org.jmrtd.lds.SODFile
import java.security.MessageDigest
import java.security.Signature
import java.security.cert.CertPathValidator
import java.security.cert.CertificateFactory
import java.security.cert.PKIXParameters
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate

/**
 * Autenticación pasiva de un eMRTD (ICAO 9303 parte 11, ADR-004).
 *
 * Está separada del módulo de React Native a propósito: aquí no hay una sola
 * referencia a Android ni al puente. Eso permite ejecutarla en la JVM contra
 * documentos sintéticos (`PassiveAuthenticatorTest`) y comprobar la criptografía
 * sin una cédula real ni un teléfono con NFC, que es la única verificación
 * disponible mientras no haya hardware de prueba.
 *
 * Las tres comprobaciones son independientes y se reportan por separado: un
 * "no verificado" tiene que poder explicarse. No son intercambiables —pasar
 * dos de tres no es "casi verificado", es NO verificado.
 */
data class PassiveAuthOutcome(
    val passed: Boolean,
    val dataGroupHashesMatch: Boolean,
    val sodSignatureValid: Boolean,
    val certificateChainTrusted: Boolean,
    val trustAnchorsInstalled: Int,
    val digestAlgorithm: String?,
    val signatureAlgorithm: String?,
    val documentSigner: String?,
    val documentSignerIssuer: String?,
    val failures: List<String>,
)

object PassiveAuthenticator {

    /**
     * @param sod EF.SOD ya parseado.
     * @param rawDataGroups bytes de cada DG **tal como se leyeron del chip**.
     *   El hash del SOD cubre el archivo completo con su tag; volver a
     *   serializar un DG parseado produce bytes distintos y la comparación
     *   fallaría siempre.
     * @param trustAnchors certificados CSCA que trae la app. Si viene vacío,
     *   la cadena no se puede comprobar y el resultado es `passed = false`:
     *   sin ancla propia, un documento falsificado valida contra su propia
     *   raíz.
     */
    fun verify(
        sod: SODFile,
        rawDataGroups: Map<Int, ByteArray>,
        trustAnchors: Set<TrustAnchor>,
    ): PassiveAuthOutcome {
        val failures = mutableListOf<String>()

        val digestsMatch = checkDataGroupHashes(sod, rawDataGroups, failures)

        val dsCertificate: X509Certificate? = try {
            sod.docSigningCertificate
        } catch (e: Exception) {
            failures.add("No se pudo extraer el certificado del Document Signer: ${describe(e)}")
            null
        }

        val signatureValid = checkSodSignature(sod, dsCertificate, failures)
        val chainTrusted = checkChain(dsCertificate, trustAnchors, failures)

        return PassiveAuthOutcome(
            passed = digestsMatch && signatureValid && chainTrusted,
            dataGroupHashesMatch = digestsMatch,
            sodSignatureValid = signatureValid,
            certificateChainTrusted = chainTrusted,
            trustAnchorsInstalled = trustAnchors.size,
            digestAlgorithm = runCatching { sod.digestAlgorithm }.getOrNull(),
            signatureAlgorithm = runCatching { sod.digestEncryptionAlgorithm }.getOrNull(),
            documentSigner = dsCertificate?.subjectX500Principal?.name,
            documentSignerIssuer = dsCertificate?.issuerX500Principal?.name,
            failures = failures,
        )
    }

    /** Paso 1: el contenido leído es el que se firmó. */
    private fun checkDataGroupHashes(
        sod: SODFile,
        rawDataGroups: Map<Int, ByteArray>,
        failures: MutableList<String>,
    ): Boolean {
        if (rawDataGroups.isEmpty()) {
            failures.add("No se leyó ningún data group que comparar contra el SOD.")
            return false
        }

        val storedHashes = try {
            sod.dataGroupHashes
        } catch (e: Exception) {
            failures.add("El SOD no expone la lista de hashes: ${describe(e)}")
            return false
        }

        var allMatch = true
        for ((number, raw) in rawDataGroups.entries.sortedBy { it.key }) {
            val label = "DG$number"
            val expected = storedHashes[number]
            if (expected == null) {
                failures.add("El SOD no declara ningún hash para $label.")
                allMatch = false
                continue
            }
            val actual = try {
                MessageDigest.getInstance(sod.digestAlgorithm).digest(raw)
            } catch (e: Exception) {
                failures.add("No se pudo calcular el hash de $label: ${describe(e)}")
                allMatch = false
                continue
            }
            if (!actual.contentEquals(expected)) {
                failures.add("El contenido de $label no coincide con su hash firmado en el SOD.")
                allMatch = false
            }
        }
        return allMatch
    }

    /** Paso 2: la firma del SOD verifica con la clave pública del DS. */
    private fun checkSodSignature(
        sod: SODFile,
        dsCertificate: X509Certificate?,
        failures: MutableList<String>,
    ): Boolean {
        if (dsCertificate == null) {
            failures.add("El SOD no incluye el certificado del Document Signer.")
            return false
        }
        return try {
            val signature = Signature.getInstance(sod.digestEncryptionAlgorithm)
            // RSASSA-PSS lleva sus parámetros fuera del OID del algoritmo; sin
            // aplicarlos, una firma legítima se rechazaría.
            runCatching { sod.digestEncryptionAlgorithmParams }
                .getOrNull()
                ?.let { params -> runCatching { signature.setParameter(params) } }
            signature.initVerify(dsCertificate.publicKey)
            signature.update(sod.eContent)
            val valid = signature.verify(sod.encryptedDigest)
            if (!valid) {
                failures.add("La firma del SOD no verifica con la clave del Document Signer.")
            }
            valid
        } catch (e: Exception) {
            failures.add("No se pudo verificar la firma del SOD: ${describe(e)}")
            false
        }
    }

    /** Paso 3: ese DS lo emitió una CSCA en la que nosotros confiamos. */
    private fun checkChain(
        dsCertificate: X509Certificate?,
        trustAnchors: Set<TrustAnchor>,
        failures: MutableList<String>,
    ): Boolean {
        if (trustAnchors.isEmpty()) {
            failures.add(
                "No hay ningún certificado CSCA instalado en la app: no se puede comprobar " +
                    "que la cédula la firmó el Registro Civil de Chile."
            )
            return false
        }
        if (dsCertificate == null) {
            return false
        }
        return try {
            dsCertificate.checkValidity()
            val factory = CertificateFactory.getInstance("X.509")
            val path = factory.generateCertPath(listOf(dsCertificate))
            val params = PKIXParameters(trustAnchors).apply {
                // Sin CRL ni OCSP: el teléfono puede estar sin red al leer la
                // cédula. La revocación de un DS se cubre actualizando la
                // master list (riesgo declarado en ADR-004); fingir aquí una
                // consulta en línea que no se hizo sería peor que omitirla.
                isRevocationEnabled = false
            }
            CertPathValidator.getInstance("PKIX").validate(path, params)
            true
        } catch (e: Exception) {
            failures.add(
                "El certificado del documento no encadena con la CSCA configurada: ${describe(e)}"
            )
            false
        }
    }

    /** Diagnóstico sin datos del titular: los errores acaban en logs. */
    private fun describe(e: Exception): String {
        val detail = e.message
        return if (detail.isNullOrBlank()) e.javaClass.simpleName else "${e.javaClass.simpleName}: $detail"
    }
}
