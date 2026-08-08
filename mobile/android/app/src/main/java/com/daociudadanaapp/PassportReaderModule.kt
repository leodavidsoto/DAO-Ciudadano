package com.daociudadanaapp

import android.app.Activity
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.IsoDep
import android.os.Bundle
import android.util.Base64
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.bridge.WritableMap
import net.sf.scuba.smartcards.IsoDepCardService
import org.jmrtd.BACKey
import org.jmrtd.PACEKeySpec
import org.jmrtd.PassportService
import org.jmrtd.lds.CardAccessFile
import org.jmrtd.lds.PACEInfo
import org.jmrtd.lds.ActiveAuthenticationInfo
import org.jmrtd.lds.SODFile
import org.jmrtd.lds.icao.DG14File
import org.jmrtd.lds.icao.DG15File
import org.jmrtd.lds.icao.DG1File
import org.jmrtd.lds.icao.DG2File
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.security.Security
import java.security.cert.CertificateFactory
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate
import java.util.Timer
import java.util.TimerTask
import java.util.GregorianCalendar
import java.util.TimeZone
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Lectura eMRTD de la cédula chilena: PACE con CAN + Passive Authentication.
 * ROADMAP 4.2, ADR-003 (por qué nativo y no JS) y ADR-004 (cadena de confianza).
 *
 * Qué garantiza y qué NO
 * ──────────────────────
 * `identityVerified` es el RESULTADO de tres comprobaciones, nunca una
 * constante:
 *
 *   1. los hashes de DG1/DG2 coinciden con los declarados en el EF.SOD,
 *   2. la firma del EF.SOD verifica con la clave pública del Document Signer,
 *   3. ese DS encadena hasta una CSCA que **nosotros** trajimos (assets), no
 *      la que venga dentro de la tarjeta.
 *
 * Si falta el ancla de confianza (hoy: no tenemos el certificado de la CSCA
 * de Chile), el paso 3 falla y `identityVerified` es `false` con el motivo
 * explícito. Leer datos de un chip NO es verificar identidad: sin CSCA, lo
 * único que se sabe es que alguien firmó esos datos, no que fuera el Registro
 * Civil. Devolver `true` ahí sería exactamente la capacidad fingida que
 * docs/HANDOFF.md prohíbe.
 *
 * Autenticación Activa (ICAO 9303-11 §6.1)
 * ────────────────────────────────────────
 * La Pasiva demuestra que Chile firmó esos datos; no demuestra que el chip
 * esté aquí. Si el servidor manda un desafío, se lee EF.DG15 y se le pide al
 * chip que lo firme con INTERNAL AUTHENTICATE. La firma NO se verifica aquí:
 * viaja en crudo al backend, que es quien tiene el desafío original y quien
 * comprueba que la clave de DG15 esté declarada en el EF.SOD. Un veredicto
 * calculado en este teléfono no es evidencia que nadie más pueda comprobar.
 *
 * Si el documento no trae DG15, no admite Autenticación Activa y se dice tal
 * cual (`supported: false`, con motivo). No se inventa una firma ni se
 * devuelve `performed: true` por defecto.
 *
 * El CAN es un secreto de la tarjeta: no se registra en logs ni se devuelve.
 */
class PassportReaderModule(reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext) {

    companion object {
        private const val MODULE_NAME = "PassportReader"

        /** Carpeta de assets con los certificados CSCA en DER o PEM. */
        private const val CSCA_ASSET_DIR = "csca"

        /** ICAO 9303-11 §6.1: el desafío de la AA son 8 bytes. */
        private const val ACTIVE_AUTH_CHALLENGE_BYTES = 8

        /** Espera máxima a que el ciudadano acerque la cédula. */
        private const val TAG_DISCOVERY_TIMEOUT_MS = 60_000L

        /**
         * Los chips eMRTD son lentos leyendo DG2 (la foto son decenas de KB
         * sobre secure messaging). El valor por defecto de IsoDep deja
         * transacciones a medias y el error resultante no dice nada útil.
         */
        private const val ISODEP_TIMEOUT_MS = 20_000

        init {
            // BouncyCastle: el que trae Android (Conscrypt) no cubre todos los
            // algoritmos de firma que aparecen en un SOD (por ejemplo
            // SHA256withRSAandMGF1). Se inserta con prioridad para que
            // Signature/MessageDigest lo encuentren primero.
            try {
                Security.removeProvider("BC")
                Security.insertProviderAt(
                    org.bouncycastle.jce.provider.BouncyCastleProvider(), 1
                )
            } catch (_: Exception) {
                // Si falla, las comprobaciones criptográficas lo reportarán;
                // no se silencia el resultado, solo el registro del proveedor.
            }
        }
    }

    override fun getName(): String = MODULE_NAME

    /** Una sola resolución por sesión: el callback NFC puede reentrar. */
    private class SingleShotPromise(private val promise: Promise) {
        private val done = AtomicBoolean(false)

        fun resolve(value: WritableMap): Boolean {
            if (done.compareAndSet(false, true)) {
                promise.resolve(value)
                return true
            }
            return false
        }

        fun reject(code: String, message: String): Boolean {
            if (done.compareAndSet(false, true)) {
                promise.reject(code, message)
                return true
            }
            return false
        }

        fun isDone(): Boolean = done.get()
    }

    /**
     * @param aaChallenge Desafío de Autenticación Activa en base64, emitido por
     *   el servidor. Cadena vacía = no hacer AA. NUNCA lo genera este módulo:
     *   un desafío elegido por el cliente no prueba nada, porque quien captura
     *   una lectura captura también el par desafío+firma y puede reenviarlo.
     */
    @ReactMethod
    fun startPACESession(
        can: String,
        dob: String,
        doe: String,
        aaChallenge: String,
        promise: Promise,
    ) {
        val once = SingleShotPromise(promise)

        val challenge: ByteArray? = if (aaChallenge.isBlank()) {
            null
        } else {
            try {
                Base64.decode(aaChallenge, Base64.NO_WRAP).also {
                    // 8 bytes es lo que el chip espera en INTERNAL AUTHENTICATE.
                    // Otro tamaño solo puede venir de un error nuestro, y mandarlo
                    // al chip produciría un fallo indescifrable.
                    if (it.size != ACTIVE_AUTH_CHALLENGE_BYTES) {
                        once.reject(
                            "E_INVALID_AA_CHALLENGE",
                            "El desafío de Autenticación Activa debe medir " +
                                "$ACTIVE_AUTH_CHALLENGE_BYTES bytes."
                        )
                        return
                    }
                }
            } catch (e: IllegalArgumentException) {
                once.reject(
                    "E_INVALID_AA_CHALLENGE",
                    "El desafío de Autenticación Activa no viene en base64 válido."
                )
                return
            }
        }

        val normalizedCan = can.trim().uppercase()
        if (normalizedCan.length < 6 || normalizedCan.length > 15 || !normalizedCan.all { it.isLetterOrDigit() }) {
            // El CAN o Número de Documento chileno suele ser alfanumérico y de hasta 9 o más caracteres.
            once.reject(
                "E_INVALID_CAN",
                "El CAN o Número de Documento debe tener entre 6 y 15 caracteres alfanuméricos."
            )
            return
        }

        val activity: Activity? = reactApplicationContext.currentActivity
        if (activity == null) {
            once.reject(
                "E_NO_ACTIVITY",
                "La app no está en primer plano; no se puede activar el lector NFC."
            )
            return
        }

        val adapter = NfcAdapter.getDefaultAdapter(reactApplicationContext)
        if (adapter == null) {
            once.reject("E_NFC_UNAVAILABLE", "Este dispositivo no tiene NFC.")
            return
        }
        if (!adapter.isEnabled) {
            once.reject(
                "E_NFC_DISABLED",
                "El NFC está apagado. Actívalo en los ajustes del sistema."
            )
            return
        }

        val timer = Timer("passport-reader-timeout", true)

        val callback = NfcAdapter.ReaderCallback { tag ->
            // Este callback corre en un hilo de binder, no en el principal:
            // se puede bloquear leyendo el chip sin congelar la UI.
            if (once.isDone()) return@ReaderCallback
            try {
                val result = readDocument(tag, normalizedCan, dob, doe, challenge)
                once.resolve(result)
            } catch (e: PassportReadError) {
                once.reject(e.code, e.message ?: "Error leyendo la cédula.")
            } catch (e: Throwable) {
                // Perder la tarjeta a mitad de la lectura NO es un CAN
                // equivocado: el canal puede haberse abierto y caerse después,
                // leyendo EF.CardAccess o cualquier data group. Mandarlo como
                // fallo de PACE hace que la app le diga al ciudadano que revise
                // unos dígitos que estaban bien, cuando lo que pasó es que
                // movió la cédula.
                once.reject(
                    if (isTagLost(e)) "E_TAG_LOST" else "E_PACE_FAILED",
                    describeFailure(e)
                )
            } finally {
                timer.cancel()
                disableReader(activity, adapter)
            }
        }

        val extras = Bundle().apply {
            // Sondear la presencia con menos frecuencia: el chip pierde el
            // canal seguro si se le interrumpe a mitad de una lectura larga.
            putInt(NfcAdapter.EXTRA_READER_PRESENCE_CHECK_DELAY, 1000)
        }

        try {
            adapter.enableReaderMode(
                activity,
                callback,
                NfcAdapter.FLAG_READER_NFC_A or
                    NfcAdapter.FLAG_READER_NFC_B or
                    NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
                extras,
            )
        } catch (e: Exception) {
            timer.cancel()
            once.reject("E_NFC_READER_MODE", describeFailure(e))
            return
        }

        timer.schedule(object : TimerTask() {
            override fun run() {
                if (once.reject(
                        "E_TIMEOUT",
                        "No se detectó ninguna cédula. Apóyala en la parte trasera del teléfono."
                    )
                ) {
                    disableReader(activity, adapter)
                }
                timer.cancel()
            }
        }, TAG_DISCOVERY_TIMEOUT_MS)
    }

    /** Cancela el modo lector; debe ejecutarse en el hilo de la UI. */
    private fun disableReader(activity: Activity, adapter: NfcAdapter) {
        activity.runOnUiThread {
            try {
                adapter.disableReaderMode(activity)
            } catch (_: Exception) {
                // La actividad puede haberse destruido mientras se leía.
            }
        }
    }

    private class PassportReadError(val code: String, message: String) : Exception(message)

    /**
     * Flujo completo: PACE, lectura de DG1/DG2/SOD y autenticación pasiva.
     *
     * Los DG se leen ADEMÁS en crudo porque el hash del SOD cubre el archivo
     * tal cual está en el chip, no el objeto ya parseado: volver a serializar
     * el DG1 daría bytes distintos y la comprobación fallaría siempre.
     */
    private fun readDocument(
        tag: Tag,
        can: String,
        dob: String,
        doe: String,
        aaChallenge: ByteArray?,
    ): WritableMap {
        val isoDep = IsoDep.get(tag)
            ?: throw PassportReadError(
                "E_TAG_NOT_SUPPORTED",
                "Ese chip no es un documento de identidad legible (no soporta ISO-DEP)."
            )
        isoDep.timeout = ISODEP_TIMEOUT_MS

        val cardService = IsoDepCardService(isoDep)
        val service = PassportService(
            cardService,
            PassportService.NORMAL_MAX_TRANCEIVE_LENGTH,
            PassportService.DEFAULT_MAX_BLOCKSIZE,
            false, // SFI deshabilitado: no todos los chips lo implementan
            false, // no exigir MAC antes de abrir el canal seguro
        )

        try {
            service.open()

            // EF.CardAccess es legible sin autenticar y declara qué variante de
            // PACE soporta el chip. Fijar el OID a mano sería adivinar.
            val paceInfo = readPaceInfo(service)
                ?: throw PassportReadError(
                    "E_PACE_UNSUPPORTED",
                    "El chip no publica parámetros PACE; no se puede abrir el canal seguro."
                )

            try {
                val keySpec = if (dob.isNotEmpty() && doe.isNotEmpty()) {
                    PACEKeySpec.createMRZKey(BACKey(can, dob, doe))
                } else {
                    PACEKeySpec.createCANKey(can)
                }
                service.doPACE(
                    keySpec,
                    paceInfo.objectIdentifier,
                    PACEInfo.toParameterSpec(paceInfo.parameterId),
                    null,
                )
            } catch (e: Exception) {
                // El motivo más frecuente es un CAN equivocado, y el chip no
                // lo distingue de otros fallos. Se dice como hipótesis, no
                // como hecho.
                throw PassportReadError(
                    "E_PACE_FAILED",
                    "No se pudo abrir el canal seguro con ese CAN. Revisa el número impreso " +
                        "en la cédula y vuelve a intentarlo. (${describeFailure(e)})"
                )
            }

            service.sendSelectApplet(true)

            val dg1Raw = readFile(service, PassportService.EF_DG1, "DG1")
            val dg2Raw = readFile(service, PassportService.EF_DG2, "DG2")
            val sodRaw = readFile(service, PassportService.EF_SOD, "EF.SOD")

            val dg1 = DG1File(ByteArrayInputStream(dg1Raw))
            val sod = SODFile(ByteArrayInputStream(sodRaw))

            // El SOD dice qué data groups declara el documento. Preguntárselo a
            // él, y no intentar la lectura a ver qué pasa, evita confundir "no
            // admite AA" con "se movió la cédula".
            val declaredDataGroups = try {
                sod.dataGroupHashes.keys.map { it.toInt() }.toSet()
            } catch (_: Exception) {
                emptySet<Int>()
            }

            val activeAuth = performActiveAuthentication(
                service, declaredDataGroups, aaChallenge
            )

            // DG14/DG15 entran en la Autenticación Pasiva como cualquier otro
            // archivo: es lo que liga la clave del chip a la firma del Registro
            // Civil. Sin eso, la firma de la AA la podría producir cualquiera
            // con su propia clave.
            val verifiedGroups = mutableMapOf(1 to dg1Raw, 2 to dg2Raw)
            activeAuth.dg15Raw?.let { verifiedGroups[15] = it }
            activeAuth.dg14Raw?.let { verifiedGroups[14] = it }

            val outcome = PassiveAuthenticator.verify(
                sod,
                verifiedGroups,
                loadTrustAnchors(),
            )
            val mrz = dg1.mrzInfo
            val issuingStateIsChile = mrz.issuingState.orEmpty()
                .trim('<').uppercase() == "CHL"
            val documentProfileIsIdentityCard = mrz.documentCode.orEmpty()
                .trim().uppercase().startsWith("I")
            val documentNotExpired = isUnexpiredMRZDate(mrz.dateOfExpiry.orEmpty())
            val countrySigningCertificateSubject = outcome.documentSignerIssuer.orEmpty()
            val countrySigningCertificateIsChile =
                isApprovedChileanCSCASubject(countrySigningCertificateSubject)
            val passed = outcome.passed &&
                issuingStateIsChile &&
                documentProfileIsIdentityCard &&
                documentNotExpired &&
                countrySigningCertificateIsChile

            return Arguments.createMap().apply {
                // El veredicto criptográfico, nunca una constante.
                putBoolean("identityVerified", passed)
                putMap(
                    "data",
                    if (passed) buildData(dg1, dg2Raw) else Arguments.createMap()
                )
                // Archivos EN CRUDO para que el backend repita la Autenticación
                // Pasiva por su cuenta. El servidor no acepta veredictos del
                // cliente, y el hash del SOD cubre el archivo tal como está en
                // el chip: reserializar un DG ya parseado daría otros bytes.
                // Solo viajan si la verificación local pasó — una lectura que
                // no verifica no tiene nada que mandar a ningún lado.
                putMap(
                    "files",
                    if (passed) {
                        buildFiles(sodRaw, dg1Raw, dg2Raw, activeAuth)
                    } else {
                        Arguments.createMap()
                    }
                )
                // Viaja pase o no la verificación local: si el chip no admite
                // AA, la app tiene que poder decirlo en vez de callarse.
                putMap("activeAuthentication", activeAuth.toWritableMap(passed))
                putMap(
                    "verification",
                    toWritableMap(
                        outcome,
                        passed,
                        issuingStateIsChile,
                        documentProfileIsIdentityCard,
                        documentNotExpired,
                        countrySigningCertificateIsChile,
                        countrySigningCertificateSubject,
                    )
                )
            }
        } finally {
            try {
                service.close()
            } catch (_: Exception) {
                // Cerrar es best-effort: la tarjeta puede haberse retirado.
            }
        }
    }

    private fun readPaceInfo(service: PassportService): PACEInfo? {
        val stream: InputStream = service.getInputStream(PassportService.EF_CARD_ACCESS)
        val cardAccess = CardAccessFile(stream)
        return cardAccess.securityInfos.filterIsInstance<PACEInfo>().firstOrNull()
    }

    private fun readFile(service: PassportService, fileId: Short, label: String): ByteArray {
        try {
            return service.getInputStream(fileId).use { it.readBytes() }
        } catch (e: Exception) {
            throw PassportReadError(
                "E_READ_FAILED",
                "No se pudo leer $label de la cédula. Mantén la tarjeta apoyada sin moverla. " +
                    "(${describeFailure(e)})"
            )
        }
    }

    /**
     * Traduce el veredicto de [PassiveAuthenticator] al puente.
     *
     * La criptografía vive en esa clase, sin dependencias de Android, para que
     * pueda ejecutarse en la JVM contra documentos sintéticos. Aquí solo se
     * mapea a WritableMap: el detalle por paso viaja entero porque una UI que
     * solo sabe "falló" no puede decirle al ciudadano si el problema es su
     * cédula o nuestra configuración.
     */
    private fun toWritableMap(
        outcome: PassiveAuthOutcome,
        passed: Boolean,
        issuingStateIsChile: Boolean,
        documentProfileIsIdentityCard: Boolean,
        documentNotExpired: Boolean,
        countrySigningCertificateIsChile: Boolean,
        countrySigningCertificateSubject: String,
    ): WritableMap {
        val failures = Arguments.createArray()
        outcome.failures.forEach { failures.pushString(it) }

        return Arguments.createMap().apply {
            putBoolean("passed", passed)
            putBoolean("dataGroupHashesMatch", outcome.dataGroupHashesMatch)
            putBoolean("sodSignatureValid", outcome.sodSignatureValid)
            putBoolean("certificateChainTrusted", outcome.certificateChainTrusted)
            putBoolean("paceEstablished", true)
            putBoolean("requiredDataGroupsPresent", true)
            putBoolean("issuingStateIsChile", issuingStateIsChile)
            putBoolean("documentProfileIsIdentityCard", documentProfileIsIdentityCard)
            putBoolean("documentNotExpired", documentNotExpired)
            putBoolean("countrySigningCertificateIsChile", countrySigningCertificateIsChile)
            putInt("trustAnchorsInstalled", outcome.trustAnchorsInstalled)
            putString("digestAlgorithm", outcome.digestAlgorithm)
            putString("signatureAlgorithm", outcome.signatureAlgorithm)
            putString("documentSigner", outcome.documentSigner)
            putString("documentSignerIssuer", outcome.documentSignerIssuer)
            putString("countrySigningCertificateSubject", countrySigningCertificateSubject)
            putArray("failures", failures)
        }
    }

    /**
     * Certificados CSCA empaquetados en `assets/csca/`.
     *
     * NUNCA se toma la CSCA de la propia tarjeta: un documento falsificado
     * traería su propia raíz y la validación se volvería un espejo (ADR-004).
     */
    private fun loadTrustAnchors(): Set<TrustAnchor> {
        val anchors = mutableSetOf<TrustAnchor>()
        val assets = reactApplicationContext.assets
        val files = try {
            assets.list(CSCA_ASSET_DIR) ?: emptyArray()
        } catch (_: Exception) {
            emptyArray()
        }
        val factory = CertificateFactory.getInstance("X.509")
        for (name in files) {
            if (!name.endsWith(".cer", true) && !name.endsWith(".pem", true) &&
                !name.endsWith(".der", true) && !name.endsWith(".crt", true)
            ) {
                continue
            }
            try {
                assets.open("$CSCA_ASSET_DIR/$name").use { input ->
                    val certificate = factory.generateCertificate(input) as X509Certificate
                    if (isApprovedChileanCSCASubject(certificate.subjectX500Principal.name) &&
                        isSelfSigned(certificate)
                    ) {
                        anchors.add(TrustAnchor(certificate, null))
                    }
                }
            } catch (_: Exception) {
                // Un archivo ilegible no puede degradar la validación de los
                // demás; simplemente no aporta ancla.
            }
        }
        return anchors
    }

    /**
     * Resultado de intentar la Autenticación Activa. `performed` solo es
     * `true` si el chip devolvió una firma; `reason` explica cualquier otro
     * caso. No hay ningún camino que devuelva `true` sin firma.
     */
    private class ActiveAuthAttempt(
        val requested: Boolean,
        val supported: Boolean,
        val performed: Boolean,
        val signature: ByteArray? = null,
        val dg15Raw: ByteArray? = null,
        val dg14Raw: ByteArray? = null,
        val reason: String? = null,
    ) {
        fun toWritableMap(passed: Boolean): WritableMap = Arguments.createMap().apply {
            putBoolean("requested", requested)
            putBoolean("supported", supported)
            putBoolean("performed", performed)
            // La firma solo sale si la verificación local pasó, igual que los
            // archivos: una lectura sin verificar no tiene nada que mandar.
            if (performed && passed && signature != null) {
                putString("signature", Base64.encodeToString(signature, Base64.NO_WRAP))
            }
            reason?.let { putString("reason", it) }
        }
    }

    /**
     * Lee EF.DG15 y le pide al chip que firme el desafío del servidor.
     *
     * Aquí NO se verifica la firma. El backend es quien conserva el desafío
     * original y quien comprueba que la clave de DG15 esté declarada en el
     * EF.SOD; una comprobación hecha solo en este teléfono es una sugerencia,
     * no evidencia (es exactamente el fallo que arregló `passive_auth.py`).
     */
    private fun performActiveAuthentication(
        service: PassportService,
        declaredDataGroups: Set<Int>,
        challenge: ByteArray?,
    ): ActiveAuthAttempt {
        if (challenge == null) {
            return ActiveAuthAttempt(
                requested = false,
                supported = declaredDataGroups.contains(15),
                performed = false,
                reason = "El servidor no pidió Autenticación Activa en esta lectura.",
            )
        }
        if (declaredDataGroups.isNotEmpty() && !declaredDataGroups.contains(15)) {
            // Un documento sin DG15 no admite AA. Decirlo es información
            // verdadera; fingir que sí y no mandar firma sería peor.
            return ActiveAuthAttempt(
                requested = true,
                supported = false,
                performed = false,
                reason = "El documento no incluye EF.DG15: no admite Autenticación Activa.",
            )
        }

        val dg15Raw = try {
            readFile(service, PassportService.EF_DG15, "DG15")
        } catch (e: PassportReadError) {
            return ActiveAuthAttempt(
                requested = true,
                supported = false,
                performed = false,
                reason = "No se pudo leer EF.DG15: ${e.message}",
            )
        }

        val publicKey = try {
            DG15File(ByteArrayInputStream(dg15Raw)).publicKey
        } catch (e: Exception) {
            return ActiveAuthAttempt(
                requested = true,
                supported = false,
                performed = false,
                dg15Raw = dg15Raw,
                reason = "EF.DG15 no contiene una clave pública legible: ${describeFailure(e)}",
            )
        }

        // DG14 solo hace falta cuando el chip firma con ECDSA: ahí es donde
        // ICAO pone el hash, y no hay valor por defecto que valga.
        var dg14Raw: ByteArray? = null
        var digestAlgorithm = "SHA-1"
        var signatureAlgorithm = "SHA1WithRSA/ISO9796-2"
        if (declaredDataGroups.isEmpty() || declaredDataGroups.contains(14)) {
            dg14Raw = try {
                readFile(service, PassportService.EF_DG14, "DG14")
            } catch (_: PassportReadError) {
                null
            }
        }
        dg14Raw?.let { raw ->
            try {
                val info = DG14File(ByteArrayInputStream(raw))
                    .activeAuthenticationInfos
                    .firstOrNull()
                info?.signatureAlgorithmOID?.let { oid ->
                    signatureAlgorithm = oid
                    digestAlgorithm = digestForSignatureOID(oid) ?: digestAlgorithm
                }
            } catch (_: Exception) {
                // DG14 ilegible: el backend decidirá. No se descarta el archivo
                // —su hash sigue estando en el SOD— ni se inventa un algoritmo.
            }
        }

        return try {
            val result = service.doAA(
                publicKey, digestAlgorithm, signatureAlgorithm, challenge
            )
            ActiveAuthAttempt(
                requested = true,
                supported = true,
                performed = true,
                signature = result.response,
                dg15Raw = dg15Raw,
                dg14Raw = dg14Raw,
            )
        } catch (e: Exception) {
            ActiveAuthAttempt(
                requested = true,
                supported = true,
                performed = false,
                dg15Raw = dg15Raw,
                dg14Raw = dg14Raw,
                reason = "El chip rechazó INTERNAL AUTHENTICATE: ${describeFailure(e)}",
            )
        }
    }

    /** Hash que declara un OID de firma plana ECDSA de BSI TR-03111. */
    private fun digestForSignatureOID(oid: String): String? = when (oid) {
        ActiveAuthenticationInfo.ECDSA_PLAIN_SHA1_OID -> "SHA-1"
        ActiveAuthenticationInfo.ECDSA_PLAIN_SHA224_OID -> "SHA-224"
        ActiveAuthenticationInfo.ECDSA_PLAIN_SHA256_OID -> "SHA-256"
        ActiveAuthenticationInfo.ECDSA_PLAIN_SHA384_OID -> "SHA-384"
        ActiveAuthenticationInfo.ECDSA_PLAIN_SHA512_OID -> "SHA-512"
        else -> null
    }

    /**
     * EF.SOD y los data groups en base64, sin saltos de línea.
     *
     * NO_WRAP importa: `Base64.DEFAULT` mete '\n' cada 76 caracteres y el
     * decodificador estricto del backend rechazaría la cadena.
     */
    private fun buildFiles(
        sodRaw: ByteArray,
        dg1Raw: ByteArray,
        dg2Raw: ByteArray,
        activeAuth: ActiveAuthAttempt,
    ): WritableMap = Arguments.createMap().apply {
        putString("sod", Base64.encodeToString(sodRaw, Base64.NO_WRAP))
        putString("dg1", Base64.encodeToString(dg1Raw, Base64.NO_WRAP))
        putString("dg2", Base64.encodeToString(dg2Raw, Base64.NO_WRAP))
        // Solo se envían si de verdad se leyeron. Un DG15 ausente tiene que
        // llegar al backend como ausente, no como una cadena vacía que su
        // decodificador estricto interpretaría como un archivo corrupto.
        activeAuth.dg15Raw?.let {
            putString("dg15", Base64.encodeToString(it, Base64.NO_WRAP))
        }
        activeAuth.dg14Raw?.let {
            putString("dg14", Base64.encodeToString(it, Base64.NO_WRAP))
        }
    }

    private fun buildData(dg1: DG1File, dg2Raw: ByteArray): WritableMap {
        val mrz = dg1.mrzInfo
        return Arguments.createMap().apply {
            putString("documentNumber", mrz.documentNumber.orEmpty().trim('<'))
            putString("firstName", mrz.secondaryIdentifier.orEmpty().replace('<', ' ').trim())
            putString("lastName", mrz.primaryIdentifier.orEmpty().replace('<', ' ').trim())
            putString("dateOfBirth", mrz.dateOfBirth.orEmpty())
            putString("dateOfExpiry", mrz.dateOfExpiry.orEmpty())
            putString("nationality", mrz.nationality.orEmpty().trim('<'))
            putString("issuingState", mrz.issuingState.orEmpty().trim('<'))
            putString("sex", mrz.gender?.toString().orEmpty())
            // El RUT no tiene un campo propio en la MRZ: viaja en los datos
            // opcionales y su formato exacto en la cédula chilena no está
            // verificado contra un documento real. Se exponen en crudo y NO se
            // adivina un `rut`: inventar el mapeo aquí sería fabricar el dato
            // de identidad más sensible de todos.
            putString("personalNumber", mrz.personalNumber.orEmpty().trim('<'))
            putString("optionalData1", mrz.optionalData1.orEmpty().trim('<'))
            putString("optionalData2", mrz.optionalData2.orEmpty().trim('<'))
            putMap("photo", extractPhoto(dg2Raw))
        }
    }

    /**
     * Ancla sí/no comprobando la FIRMA, no comparando `subject` con `issuer`.
     *
     * Desde 2024 el Registro Civil rota la clave de su CSCA conservando el
     * mismo DN, así que el *link certificate* que la generación anterior emite
     * sobre la clave nueva tiene subject idéntico a su issuer. Con la prueba
     * por DN ese eslabón se instalaría como raíz: la app confiaría en él por
     * su nombre y no porque nadie demostrara nada. Aquí sólo entra un
     * certificado que verifique con su propia clave pública.
     */
    private fun isSelfSigned(certificate: X509Certificate): Boolean {
        return try {
            certificate.verify(certificate.publicKey)
            true
        } catch (_: Exception) {
            false
        }
    }

    private fun isApprovedChileanCSCASubject(subject: String): Boolean {
        val fields = subject.split(',').map { it.trim().replace(" ", "").uppercase() }
        return fields.contains("C=CL") &&
            subject.uppercase().contains("SERVICIO DE REGISTRO CIVIL")
    }

    private fun isUnexpiredMRZDate(value: String): Boolean {
        if (!value.matches(Regex("^[0-9]{6}$"))) return false
        return try {
            val expiry = GregorianCalendar(TimeZone.getTimeZone("UTC")).apply {
                isLenient = false
                clear()
                set(
                    2000 + value.substring(0, 2).toInt(),
                    value.substring(2, 4).toInt() - 1,
                    value.substring(4, 6).toInt(),
                )
            }.timeInMillis
            val today = GregorianCalendar(TimeZone.getTimeZone("UTC")).apply {
                set(GregorianCalendar.HOUR_OF_DAY, 0)
                set(GregorianCalendar.MINUTE, 0)
                set(GregorianCalendar.SECOND, 0)
                set(GregorianCalendar.MILLISECOND, 0)
            }.timeInMillis
            expiry >= today
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Foto del DG2. Se devuelve con su MIME real: los eMRTD suelen guardarla
     * en JPEG2000, que Android no decodifica de fábrica. Rotularla como JPEG
     * haría que la UI mostrara una imagen rota sin explicación.
     */
    private fun extractPhoto(dg2Raw: ByteArray): WritableMap {
        val map = Arguments.createMap()
        try {
            val dg2 = DG2File(ByteArrayInputStream(dg2Raw))
            val imageInfo = dg2.faceInfos
                .flatMap { it.faceImageInfos }
                .firstOrNull()
            if (imageInfo == null) {
                map.putBoolean("available", false)
                map.putString("reason", "El DG2 no contiene ninguna imagen facial.")
                return map
            }
            val bytes = ByteArray(imageInfo.imageLength)
            imageInfo.imageInputStream.use { input ->
                var read = 0
                while (read < bytes.size) {
                    val n = input.read(bytes, read, bytes.size - read)
                    if (n <= 0) break
                    read += n
                }
                if (read != bytes.size) {
                    map.putBoolean("available", false)
                    map.putString("reason", "La imagen del DG2 llegó incompleta.")
                    return map
                }
            }
            map.putBoolean("available", true)
            map.putString("mimeType", imageInfo.mimeType.orEmpty())
            map.putString("base64", Base64.encodeToString(bytes, Base64.NO_WRAP))
        } catch (e: Exception) {
            map.putBoolean("available", false)
            map.putString("reason", "No se pudo extraer la foto: ${describeFailure(e)}")
        }
        return map
    }

    /**
     * Mensaje de diagnóstico sin datos del titular ni el CAN: los errores
     * acaban en logs y en pantallas de soporte.
     */
    /**
     * ¿La cédula se despegó del teléfono a mitad de la lectura?
     *
     * Se recorre la cadena de causas porque JMRTD envuelve la
     * `TagLostException` de Android dentro de `CardServiceException` y esta
     * dentro de `IOException`; mirar solo la excepción de arriba no la ve.
     */
    private fun isTagLost(e: Throwable): Boolean {
        var current: Throwable? = e
        while (current != null) {
            if (current is android.nfc.TagLostException) return true
            current = current.cause
        }
        return false
    }

    private fun describeFailure(e: Throwable): String {
        android.util.Log.e("PassportReader", "Native error", e)
        var current: Throwable? = e
        val sb = java.lang.StringBuilder()
        while (current != null) {
            sb.append(current.javaClass.simpleName)
            if (!current.message.isNullOrBlank()) {
                sb.append(": ").append(current.message)
            }
            current = current.cause
            if (current != null) sb.append(" -> ")
        }
        return sb.toString()
    }
}
