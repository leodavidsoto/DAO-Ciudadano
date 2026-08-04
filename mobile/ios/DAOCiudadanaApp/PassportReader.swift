import Foundation
import CoreNFC
import NFCPassportReader

/**
 * Lectura eMRTD en iOS (ROADMAP 4.2, ADR-003).
 *
 * ESTADO: la sesión NFC y la detección del chip están implementadas y son
 * probables en un dispositivo real. El handshake PACE **no**, y no se simula.
 *
 * Por qué no está PACE
 * ────────────────────
 * ADR-003 eligió envolver `NFCPassportReader` (Swift, open source) en vez de
 * escribir el stack criptográfico a mano. Esa dependencia **no está en el
 * proyecto**: `ios/Podfile` y `Podfile.lock` solo traen `react-native-nfc-manager`.
 *
 * Escribir PACE aquí desde cero —parseo ASN.1 de EF.CardAccess, KDF sobre el
 * CAN, descifrado del nonce, mapeo genérico sobre curva elíptica, tokens CMAC
 * y después Secure Messaging con AES-CBC y contador SSC— es exactamente la
 * "Opción 1" que ADR-003 descartó por riesgo técnico inaceptable. Hacerlo sin
 * una cédula real contra la que probar, en el camino que decide si alguien es
 * ciudadano verificado, sería peor que no tenerlo: un error ahí no se ve, se
 * confía.
 *
 * Por eso este módulo falla con un código propio y explícito
 * (`E_PACE_UNSUPPORTED_PLATFORM`) en lugar de devolver datos o un
 * `identityVerified` optimista. Lo que sí queda listo y verificable en
 * hardware: permisos, entitlement, ciclo de vida de la sesión, detección del
 * tag ISO7816 y el mapeo de errores hacia JS.
 *
 * Para completarlo:
 *   1. añadir `NFCPassportReader` (SwiftPM o CocoaPods) al proyecto iOS,
 *   2. sustituir el punto marcado abajo por su API de PACE + lectura de DG/SOD,
 *   3. replicar la autenticación pasiva de `PassportReaderModule.kt`: hashes
 *      de los DG contra el SOD, firma del SOD y cadena DS -> CSCA contra un
 *      ancla propia empaquetada, NUNCA la que venga dentro de la tarjeta.
 */
@objc(PassportReader)
class PassportReader: NSObject {

  private var session: NFCTagReaderSession?
  private var resolveBlock: RCTPromiseResolveBlock?
  private var rejectBlock: RCTPromiseRejectBlock?
  private var can: String?
  /// Protege la resolución única de la promesa: los callbacks de CoreNFC
  /// llegan en su propia cola y pueden solaparse con la invalidación.
  private let lock = NSLock()

  @objc(startPACESession:withResolver:withRejecter:)
  func startPACESession(
    can: String,
    resolve: @escaping RCTPromiseResolveBlock,
    reject: @escaping RCTPromiseRejectBlock
  ) {
    let normalizedCan = can.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !normalizedCan.isEmpty,
          normalizedCan.allSatisfy({ $0.isNumber }) else {
      reject(
        "E_INVALID_CAN",
        "El CAN debe ser el número impreso en la cédula (solo dígitos).",
        nil
      )
      return
    }

    guard NFCTagReaderSession.readingAvailable else {
      reject(
        "E_NFC_UNAVAILABLE",
        "Este dispositivo no puede leer chips NFC de documentos.",
        nil
      )
      return
    }

    lock.lock()
    resolveBlock = resolve
    rejectBlock = reject
    self.can = normalizedCan
    lock.unlock()

    session = NFCTagReaderSession(pollingOption: [.iso14443], delegate: self, queue: nil)
    session?.alertMessage = "Apoya tu cédula en la parte superior del teléfono."
    session?.begin()
  }

  @objc
  static func requiresMainQueueSetup() -> Bool {
    return false
  }

  /// Master list CSCA empaquetada en la app, o `nil` si no hay ninguna.
  ///
  /// Equivalente iOS de `assets/csca/` en Android. Mientras devuelva `nil`, la
  /// autenticación pasiva falla en el paso de la cadena e `identityVerified`
  /// es `false` aunque el documento sea coherente consigo mismo. Es el
  /// comportamiento correcto: sin ancla propia, un documento falsificado se
  /// valida contra su propia raíz.
  ///
  /// Para completarlo: añadir el `.pem` de la CSCA de Chile (ICAO PKD o
  /// Registro Civil) al bundle como `cscaMasterList.pem`, verificando su
  /// huella SHA-256 por un canal distinto al de descarga. NUNCA uses el
  /// certificado que venga dentro de la propia tarjeta.
  static func bundledMasterListURL() -> URL? {
    return Bundle.main.url(forResource: "cscaMasterList", withExtension: "pem")
  }

  /// Entrega el resultado una sola vez y suelta las referencias.
  private func finish(code: String?, message: String, value: Any? = nil) {
    lock.lock()
    let resolve = resolveBlock
    let reject = rejectBlock
    resolveBlock = nil
    rejectBlock = nil
    lock.unlock()

    if let code = code {
      reject?(code, message, nil)
    } else {
      resolve?(value)
    }
  }
}

extension PassportReader: NFCTagReaderSessionDelegate {

  func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {
    // Sin acción: la lectura empieza cuando aparece un tag.
  }

  func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
    guard let tag = tags.first else {
      session.invalidate(errorMessage: "No se detectó ninguna tarjeta.")
      return
    }

    guard case .iso7816 = tag else {
      // Una tarjeta de transporte o una llave de hotel llegan hasta aquí; no
      // son documentos de identidad y hay que decirlo con precisión.
      session.invalidate(errorMessage: "Ese chip no es un documento de identidad.")
      finish(
        code: "E_TAG_NOT_SUPPORTED",
        message: "Ese chip no es un documento de identidad legible (no soporta ISO7816)."
      )
      return
    }

    session.connect(to: tag) { [weak self] error in
      guard let self = self else { return }
      if let error = error {
        session.invalidate(errorMessage: "No se pudo conectar con la cédula.")
        self.finish(
          code: "E_TAG_CONNECTION_FAILED",
          message: "No se pudo conectar con el chip: \(error.localizedDescription)"
        )
        return
      }

      guard let can = self.can else {
        session.invalidate(errorMessage: "CAN inválido.")
        self.finish(code: "E_INVALID_CAN", message: "Falta CAN para la sesión PACE.")
        return
      }

      Task {
        do {
            let nfcPassportReader = NFCPassportReader()
            let passport = try await nfcPassportReader.readPassport(mrzKey: can, tags: [.DG1, .DG2, .SOD], paceKeyReference: 0x02)
            
            var data: [String: Any] = [:]
            data["documentNumber"] = passport.documentNumber
            data["firstName"] = passport.firstName
            data["lastName"] = passport.lastName
            data["dateOfBirth"] = passport.dateOfBirth
            data["dateOfExpiry"] = passport.documentExpiryDate
            data["nationality"] = passport.nationality
            data["issuingState"] = passport.issuingAuthority
            data["sex"] = passport.gender
            data["personalNumber"] = passport.personalNumber ?? passport.optionalData

            var serialNumber = ""
            if case let .iso7816(iso7816Tag) = tag {
                serialNumber = iso7816Tag.identifier.map { String(format: "%02X", $0) }.joined()
            }
            data["serialNumber"] = serialNumber
            
            // La master list es el ancla de confianza: el equivalente iOS de
            // `assets/csca/` en Android. Sin ella no hay contra qué encadenar
            // el Document Signer, y eso NO puede dar por verificada la cédula.
            let masterListURL = Self.bundledMasterListURL()
            passport.verifyPassport(masterListURL: masterListURL)

            let hashesMatch = passport.passportDataNotTampered
            let signatureValid = passport.passportCorrectlySigned
            let chainTrusted = passport.documentSigningCertificateVerified

            // Los TRES, igual que en PassportReaderModule.kt.
            //
            // Antes esto era `hashesMatch && signatureValid`, dejando fuera la
            // cadena de confianza que sí se calculaba dos líneas más abajo. Un
            // documento falsificado que trae su propio DS y su propia CSCA
            // cumple los dos primeros —es internamente coherente— y se habría
            // reportado como identidad verificada. Es exactamente el escenario
            // que cubre el test `un documento que trae su propia raiz no se
            // valida a si mismo` en Android, y el hallazgo P-63 otra vez.
            let passed = hashesMatch && signatureValid && chainTrusted

            var failures: [String] = []
            if !hashesMatch {
                failures.append("El contenido de algún data group no coincide con su hash firmado.")
            }
            if !signatureValid {
                failures.append("La firma del SOD no verifica con la clave del Document Signer.")
            }
            if masterListURL == nil {
                failures.append(
                    "No hay master list CSCA empaquetada en la app: no se puede comprobar "
                    + "que la cédula la firmó el Registro Civil de Chile."
                )
            } else if !chainTrusted {
                failures.append(
                    "El certificado del documento no encadena con la CSCA configurada."
                )
            }

            var verification: [String: Any] = [:]
            verification["passed"] = passed
            verification["dataGroupHashesMatch"] = hashesMatch
            verification["sodSignatureValid"] = signatureValid
            verification["certificateChainTrusted"] = chainTrusted
            verification["trustAnchorsInstalled"] = masterListURL == nil ? 0 : 1
            verification["documentSigner"] = passport.documentSigningCertificate?.getSubjectName() ?? ""
            verification["documentSignerIssuer"] = passport.documentSigningCertificate?.getIssuerName() ?? ""
            verification["failures"] = failures

            let result: [String: Any] = [
                "identityVerified": passed,
                "data": data,
                "verification": verification
            ]
            
            session.invalidate()
            self.finish(code: nil, message: "", value: result)
        } catch {
            session.invalidate(errorMessage: "No se pudo leer la cédula.")
            self.finish(code: "E_PACE_FAILED", message: "Fallo al leer la cédula: \(error.localizedDescription)")
        }
      }
    }
  }

  func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
    let nfcError = error as? NFCReaderError
    let code: String
    let message: String

    switch nfcError?.code {
    case .readerSessionInvalidationErrorUserCanceled:
      code = "E_CANCELLED"
      message = "Cancelaste la lectura de la cédula."
    case .readerSessionInvalidationErrorSessionTimeout:
      code = "E_TIMEOUT"
      message = "Se agotó el tiempo de espera. Vuelve a intentarlo con la cédula apoyada."
    default:
      code = "E_NFC_SESSION_FAILED"
      message = error.localizedDescription
    }

    // Si ya se resolvió (por ejemplo, tras E_PACE_UNSUPPORTED_PLATFORM), esto
    // no hace nada: `finish` es de un solo disparo.
    finish(code: code, message: message)
  }
}
