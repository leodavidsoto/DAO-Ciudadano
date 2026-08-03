import Foundation
import CoreNFC

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
    lock.unlock()

    session = NFCTagReaderSession(pollingOption: [.iso14443], delegate: self, queue: nil)
    session?.alertMessage = "Apoya tu cédula en la parte superior del teléfono."
    session?.begin()
  }

  @objc
  static func requiresMainQueueSetup() -> Bool {
    return false
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

      // ─── Punto exacto donde falta la implementación ───
      // El canal está abierto y la tarjeta responde. Lo que no existe es el
      // stack PACE; aquí iría la llamada a la librería eMRTD.
      session.invalidate(
        errorMessage: "La verificación de cédula todavía no está disponible en iOS."
      )
      self.finish(
        code: "E_PACE_UNSUPPORTED_PLATFORM",
        message: "La lectura PACE de la cédula todavía no está implementada en iOS. "
          + "Falta integrar la librería eMRTD (ADR-003); usa Android mientras tanto."
      )
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
