package com.daociudadanaapp

import org.bouncycastle.asn1.x500.X500Name
import org.bouncycastle.asn1.x509.BasicConstraints
import org.bouncycastle.asn1.x509.Extension
import org.bouncycastle.asn1.x509.KeyUsage
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509CertificateHolder
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.jce.provider.BouncyCastleProvider
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import org.jmrtd.lds.SODFile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.BeforeClass
import org.junit.Test
import java.io.ByteArrayInputStream
import java.math.BigInteger
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Security
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate
import java.util.Date

/**
 * Autenticación pasiva contra documentos SINTÉTICOS (ROADMAP 4.2, ADR-004).
 *
 * Por qué existe este test
 * ───────────────────────
 * No hay forma de probar la lectura NFC en un emulador ni cédulas chilenas de
 * prueba a mano. Sin esto, la criptografía de `PassiveAuthenticator` sería
 * código que nadie ejecutó nunca — y es justo el código que decide si una
 * persona queda registrada como ciudadano verificado.
 *
 * Aquí se fabrica una jerarquía completa (CSCA -> Document Signer -> EF.SOD
 * firmado sobre hashes de DG reales) con las mismas librerías que corren en el
 * teléfono, y se comprueba tanto el caso bueno como cada forma de fallar.
 *
 * Lo que este test NO cubre, y hay que decirlo: el handshake PACE, el secure
 * messaging y el parseo de un DG1 real. Eso solo se puede verificar con una
 * cédula física.
 */
class PassiveAuthenticatorTest {

    companion object {
        private const val DIGEST_ALGORITHM = "SHA-256"
        private const val SIGNATURE_ALGORITHM = "SHA256withRSA"

        private lateinit var cscaKeyPair: KeyPair
        private lateinit var cscaCertificate: X509Certificate
        private lateinit var dsKeyPair: KeyPair
        private lateinit var dsCertificate: X509Certificate

        /** Una CSCA distinta: sirve para probar que NO valida cualquier raíz. */
        private lateinit var foreignCsca: X509Certificate

        @BeforeClass
        @JvmStatic
        fun setUpPki() {
            Security.addProvider(BouncyCastleProvider())

            cscaKeyPair = generateRsaKeyPair()
            cscaCertificate = selfSignedCa("CN=CSCA de prueba, C=CL", cscaKeyPair)

            dsKeyPair = generateRsaKeyPair()
            dsCertificate = signedBy(
                subject = "CN=Document Signer de prueba, C=CL",
                subjectKeyPair = dsKeyPair,
                issuerCertificate = cscaCertificate,
                issuerKey = cscaKeyPair.private,
            )

            foreignCsca = selfSignedCa("CN=CSCA de otro pais, C=XX", generateRsaKeyPair())
        }

        private fun generateRsaKeyPair(): KeyPair =
            KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()

        private fun validityWindow(): Pair<Date, Date> {
            val now = System.currentTimeMillis()
            return Date(now - 86_400_000L) to Date(now + 365L * 86_400_000L)
        }

        private fun selfSignedCa(dn: String, keyPair: KeyPair): X509Certificate {
            val (notBefore, notAfter) = validityWindow()
            val name = X500Name(dn)
            val builder = JcaX509v3CertificateBuilder(
                name,
                BigInteger.valueOf(System.nanoTime()),
                notBefore,
                notAfter,
                name,
                keyPair.public,
            )
            builder.addExtension(Extension.basicConstraints, true, BasicConstraints(true))
            builder.addExtension(
                Extension.keyUsage,
                true,
                KeyUsage(KeyUsage.keyCertSign or KeyUsage.cRLSign),
            )
            val signer = JcaContentSignerBuilder(SIGNATURE_ALGORITHM)
                .setProvider("BC")
                .build(keyPair.private)
            return JcaX509CertificateConverter().setProvider("BC")
                .getCertificate(builder.build(signer))
        }

        private fun signedBy(
            subject: String,
            subjectKeyPair: KeyPair,
            issuerCertificate: X509Certificate,
            issuerKey: PrivateKey,
        ): X509Certificate {
            val (notBefore, notAfter) = validityWindow()
            // El nombre del emisor se toma del certificado YA CODIFICADO, no
            // de `subjectX500Principal.name`: reconstruirlo desde el texto
            // RFC2253 puede cambiar la codificación DER (PrintableString vs
            // UTF8String) y PKIX compara bytes, no cadenas. Con el texto, la
            // cadena no encadenaba ni siendo correcta.
            val builder = JcaX509v3CertificateBuilder(
                JcaX509CertificateHolder(issuerCertificate).subject,
                BigInteger.valueOf(System.nanoTime()),
                notBefore,
                notAfter,
                X500Name(subject),
                subjectKeyPair.public,
            )
            builder.addExtension(Extension.basicConstraints, true, BasicConstraints(false))
            builder.addExtension(
                Extension.keyUsage,
                true,
                KeyUsage(KeyUsage.digitalSignature),
            )
            val signer = JcaContentSignerBuilder(SIGNATURE_ALGORITHM)
                .setProvider("BC")
                .build(issuerKey)
            return JcaX509CertificateConverter().setProvider("BC")
                .getCertificate(builder.build(signer))
        }
    }

    /** Contenido arbitrario: la autenticación pasiva solo mira sus hashes. */
    private val dg1 = "DG1: MRZ de prueba".toByteArray()
    private val dg2 = "DG2: retrato de prueba".toByteArray()

    private fun hashes(vararg groups: Pair<Int, ByteArray>): Map<Int, ByteArray> {
        val digest = MessageDigest.getInstance(DIGEST_ALGORITHM)
        return groups.associate { (number, content) -> number to digest.digest(content) }
    }

    /**
     * Construye un EF.SOD y lo vuelve a parsear desde bytes, como haría el
     * módulo tras leerlo del chip: así el test recorre también la
     * serialización, donde ya han aparecido incompatibilidades entre
     * versiones de BouncyCastle.
     */
    private fun buildSod(
        dataGroupHashes: Map<Int, ByteArray>,
        signingKey: PrivateKey = dsKeyPair.private,
        certificate: X509Certificate = dsCertificate,
    ): SODFile {
        val sod = SODFile(
            DIGEST_ALGORITHM,
            SIGNATURE_ALGORITHM,
            dataGroupHashes,
            signingKey,
            certificate,
        )
        return SODFile(ByteArrayInputStream(sod.encoded))
    }

    private fun anchors(vararg certificates: X509Certificate): Set<TrustAnchor> =
        certificates.map { TrustAnchor(it, null) }.toSet()

    @Test
    fun `documento integro con la CSCA correcta queda verificado`() {
        val sod = buildSod(hashes(1 to dg1, 2 to dg2))

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to dg1, 2 to dg2),
            anchors(cscaCertificate),
        )

        assertTrue(outcome.failures.joinToString(), outcome.passed)
        assertTrue(outcome.dataGroupHashesMatch)
        assertTrue(outcome.sodSignatureValid)
        assertTrue(outcome.certificateChainTrusted)
        assertEquals(1, outcome.trustAnchorsInstalled)
    }

    @Test
    fun `un data group alterado invalida el documento`() {
        // El SOD se firma sobre el DG1 legítimo, pero se presenta otro.
        val sod = buildSod(hashes(1 to dg1, 2 to dg2))
        val tampered = "DG1: MRZ MANIPULADA".toByteArray()

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to tampered, 2 to dg2),
            anchors(cscaCertificate),
        )

        assertFalse(outcome.passed)
        assertFalse(outcome.dataGroupHashesMatch)
        // La firma sigue siendo válida: lo que cambió fue el contenido. Que
        // los pasos se reporten por separado es lo que permite decirlo.
        assertTrue(outcome.sodSignatureValid)
        assertTrue(outcome.failures.any { it.contains("DG1") })
    }

    @Test
    fun `sin certificado CSCA instalado no hay identidad verificada`() {
        // Estado actual de la app: assets/csca vacío.
        val sod = buildSod(hashes(1 to dg1, 2 to dg2))

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to dg1, 2 to dg2),
            emptySet(),
        )

        assertFalse(outcome.passed)
        assertFalse(outcome.certificateChainTrusted)
        assertEquals(0, outcome.trustAnchorsInstalled)
        // Los otros dos pasos sí pasan: el documento es coherente consigo
        // mismo. Eso es exactamente lo que NO basta para verificar identidad.
        assertTrue(outcome.dataGroupHashesMatch)
        assertTrue(outcome.sodSignatureValid)
        assertTrue(outcome.failures.any { it.contains("CSCA") })
    }

    @Test
    fun `una CSCA que no es la nuestra no valida el documento`() {
        val sod = buildSod(hashes(1 to dg1, 2 to dg2))

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to dg1, 2 to dg2),
            anchors(foreignCsca),
        )

        assertFalse(outcome.passed)
        assertFalse(outcome.certificateChainTrusted)
    }

    @Test
    fun `un documento que trae su propia raiz no se valida a si mismo`() {
        // El escenario de falsificación que describe ADR-004: el atacante
        // firma el SOD con un DS suyo, emitido por una CSCA suya. Todo es
        // internamente coherente; lo único que lo delata es que esa raíz no
        // es la que la app trae empaquetada.
        val rogueCscaKeys = generateRsaKeyPair()
        val rogueCsca = selfSignedCa("CN=CSCA falsificada, C=CL", rogueCscaKeys)
        val rogueDsKeys = generateRsaKeyPair()
        val rogueDs = signedBy(
            subject = "CN=Document Signer falsificado, C=CL",
            subjectKeyPair = rogueDsKeys,
            issuerCertificate = rogueCsca,
            issuerKey = rogueCscaKeys.private,
        )
        val sod = buildSod(
            hashes(1 to dg1, 2 to dg2),
            signingKey = rogueDsKeys.private,
            certificate = rogueDs,
        )

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to dg1, 2 to dg2),
            anchors(cscaCertificate),
        )

        assertFalse("Un documento autofirmado no puede quedar verificado", outcome.passed)
        assertTrue(outcome.dataGroupHashesMatch)
        assertTrue(outcome.sodSignatureValid)
        assertFalse(outcome.certificateChainTrusted)
    }

    @Test
    fun `un data group que el SOD no declara invalida el documento`() {
        // El SOD cubre DG1 y DG2; el chip entrega además un DG3 que nadie
        // firmó. Aceptarlo dejaría entrar contenido arbitrario junto a datos
        // legítimos. (JMRTD exige al menos dos hashes para construir un SOD,
        // así que el grupo no declarado tiene que ser un tercero.)
        val sod = buildSod(hashes(1 to dg1, 2 to dg2))
        val dg3 = "DG3: contenido no firmado".toByteArray()

        val outcome = PassiveAuthenticator.verify(
            sod,
            mapOf(1 to dg1, 2 to dg2, 3 to dg3),
            anchors(cscaCertificate),
        )

        assertFalse(outcome.passed)
        assertFalse(outcome.dataGroupHashesMatch)
        assertTrue(outcome.failures.any { it.contains("DG3") })
    }
}
