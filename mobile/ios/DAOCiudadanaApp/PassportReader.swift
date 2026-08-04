import CoreNFC
import Foundation
import NFCPassportReader
import React

/**
 * Puente eMRTD de iOS.
 *
 * `NFCPassportReader` es el único dueño de la sesión CoreNFC. Antes este
 * puente abría una sesión y, después de detectar el tag, pedía a la librería
 * que abriera una segunda. CoreNFC solo admite una sesión activa, por lo que
 * ese camino no podía completar una lectura real.
 *
 * La autenticación pasiva falla cerrada. Una lectura solo se considera una
 * cédula chilena verificada cuando:
 *
 * 1. los hashes de los data groups coinciden con EF.SOD;
 * 2. la firma de EF.SOD verifica con el Document Signer;
 * 3. el Document Signer encadena con una CSCA empaquetada por la aplicación;
 * 4. el documento declara a Chile como Estado emisor.
 *
 * La Master List nunca se obtiene desde el documento. El build de
 * distribución la instala como `cscaMasterList.pem` después de verificar su
 * huella SHA-256 (ver `scripts/install-csca-master-list.sh`). Si el recurso no
 * existe, el lector ni siquiera inicia y devuelve un error explícito.
 */
@objc(PassportReader)
final class PassportReaderBridge: NSObject {
  private let scanLock = NSLock()
  private var scanInFlight = false
  private var activeReader: NFCPassportReader.PassportReader?

  @objc(startPACESession:withResolver:withRejecter:)
  func startPACESession(
    can: String,
    resolve: @escaping RCTPromiseResolveBlock,
    reject: @escaping RCTPromiseRejectBlock
  ) {
    let normalizedCan = can.trimmingCharacters(in: .whitespacesAndNewlines)
    let canIsSixAsciiDigits = normalizedCan.utf8.count == 6
      && normalizedCan.utf8.allSatisfy({ byte in byte >= 48 && byte <= 57 })
    guard canIsSixAsciiDigits else {
      reject(
        "E_INVALID_CAN",
        "El CAN debe contener exactamente los 6 dígitos impresos en la cédula.",
        nil
      )
      return
    }

    guard let masterListURL = Self.bundledMasterListURL() else {
      reject(
        "E_CSCA_MASTER_LIST_MISSING",
        "Esta versión no incluye una Master List CSCA autenticada; no puede verificar cédulas.",
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

    guard beginScan() else {
      reject(
        "E_SCAN_IN_PROGRESS",
        "Ya hay una lectura de cédula en curso.",
        nil
      )
      return
    }

    Task { @MainActor [weak self] in
      guard let self else { return }
      defer { self.endScan() }

      do {
        // Inyectar el ancla ANTES de abrir CoreNFC hace que la propia lectura
        // ejecute `verifyPassport(masterListURL:)` sobre el modelo resultante.
        let reader = NFCPassportReader.PassportReader(masterListURL: masterListURL)
        self.setActiveReader(reader)
        let passport = try await reader.readPassport(
          mrzKey: normalizedCan,
          tags: [.DG1, .DG2, .SOD],
          paceKeyReference: 0x02,
          allowBACFallback: false
        )

        // Repetir la verificación de forma explícita mantiene esta frontera
        // segura aunque una versión futura de la librería deje de hacerla al
        // final de `readPassport`.
        passport.verifyPassport(masterListURL: masterListURL)

        let hashesMatch = passport.passportDataNotTampered
        let sodSignatureValid = passport.documentSigningCertificateVerified
        let certificateChainTrusted = passport.passportCorrectlySigned
        let paceEstablished: Bool
        switch passport.PACEStatus {
        case .success:
          paceEstablished = true
        default:
          paceEstablished = false
        }
        let requiredDataGroupsPresent = [DataGroupId.DG1, .DG2, .SOD]
          .allSatisfy({ passport.dataGroupsRead[$0] != nil })
        let issuingState = passport.issuingAuthority
          .trimmingCharacters(in: .whitespacesAndNewlines)
          .uppercased()
        let issuingStateIsChile = issuingState == "CHL"
        let documentProfileIsIdentityCard = passport.documentType
          .trimmingCharacters(in: .whitespacesAndNewlines)
          .uppercased()
          .hasPrefix("I")
        let trustAnchorsInstalled = Self.certificateCount(in: masterListURL)
        let countrySigningCertificate = passport.countrySigningCertificate
        let countrySigningCertificateSubject =
          countrySigningCertificate?.getSubjectName() ?? ""
        let countrySigningCertificateIsChile =
          Self.isApprovedChileanCSCASubject(countrySigningCertificateSubject)
        let documentNotExpired = Self.isUnexpiredMRZDate(passport.documentExpiryDate)

        // `documentSigningCertificateVerified` forma parte obligatoria del
        // veredicto. Una cadena válida no compensa una firma SOD inválida, ni
        // una firma interna válida compensa una cadena sin CSCA propia.
        let passed = hashesMatch
          && sodSignatureValid
          && certificateChainTrusted
          && paceEstablished
          && requiredDataGroupsPresent
          && issuingStateIsChile
          && documentProfileIsIdentityCard
          && trustAnchorsInstalled > 0
          && countrySigningCertificateIsChile
          && documentNotExpired

        var failures: [String] = []
        if !hashesMatch {
          failures.append(
            "El contenido de algún data group no coincide con su hash firmado."
          )
        }
        if !sodSignatureValid {
          failures.append(
            "La firma de EF.SOD no verifica con el certificado Document Signer."
          )
        }
        if !certificateChainTrusted {
          failures.append(
            "El Document Signer no encadena con una CSCA instalada por la aplicación."
          )
        }
        if !paceEstablished {
          failures.append(
            "PACE-CAN no se estableció; no se acepta el fallback BAC como acreditación de cédula."
          )
        }
        if !requiredDataGroupsPresent {
          failures.append(
            "La lectura no contiene DG1, DG2 y EF.SOD completos."
          )
        }
        if !issuingStateIsChile {
          failures.append(
            "El documento leído no declara a Chile como Estado emisor."
          )
        }
        if !documentProfileIsIdentityCard {
          failures.append(
            "El chip no declara un perfil de documento de identidad admitido."
          )
        }
        if trustAnchorsInstalled < 1 {
          failures.append(
            "La aplicación no tiene anclas CSCA instaladas."
          )
        }
        if !countrySigningCertificateIsChile {
          failures.append(
            "La cadena no termina en una CSCA chilena aprobada del Registro Civil."
          )
        }
        if !documentNotExpired {
          failures.append(
            "La cédula está vencida o su fecha de expiración no es válida."
          )
        }

        var data: [String: Any] = [:]
        if passed {
          data = [
            "documentNumber": passport.documentNumber,
            "firstName": passport.firstName,
            "lastName": passport.lastName,
            "dateOfBirth": passport.dateOfBirth,
            "dateOfExpiry": passport.documentExpiryDate,
            "nationality": passport.nationality,
            "issuingState": passport.issuingAuthority,
            "sex": passport.gender,
          ]
          if let personalNumber = passport.personalNumber, !personalNumber.isEmpty {
            data["personalNumber"] = personalNumber
          }
        }

        let verification: [String: Any] = [
          "passed": passed,
          "dataGroupHashesMatch": hashesMatch,
          "sodSignatureValid": sodSignatureValid,
          "certificateChainTrusted": certificateChainTrusted,
          "paceEstablished": paceEstablished,
          "requiredDataGroupsPresent": requiredDataGroupsPresent,
          "issuingStateIsChile": issuingStateIsChile,
          "documentProfileIsIdentityCard": documentProfileIsIdentityCard,
          "documentNotExpired": documentNotExpired,
          "trustAnchorsInstalled": trustAnchorsInstalled,
          "countrySigningCertificateIsChile": countrySigningCertificateIsChile,
          "countrySigningCertificateSubject": countrySigningCertificateSubject,
          "documentSigner": passport.documentSigningCertificate?.getSubjectName() ?? "",
          "documentSignerIssuer": passport.documentSigningCertificate?.getIssuerName() ?? "",
          "failures": failures,
        ]

        resolve([
          "identityVerified": passed,
          "data": data,
          "verification": verification,
        ])
      } catch {
        reject(
          "E_DOCUMENT_READ_FAILED",
          "No se pudo leer y verificar la cédula. Revisa el CAN y mantén el documento apoyado.",
          error
        )
      }
    }
  }

  @objc(cancelPACESession)
  func cancelPACESession() {
    scanLock.lock()
    let reader = activeReader
    scanLock.unlock()
    Task { @MainActor in
      reader?.cancelPassportRead()
    }
  }

  @objc
  static func requiresMainQueueSetup() -> Bool {
    return false
  }

  static func bundledMasterListURL() -> URL? {
    return Bundle.main.url(forResource: "cscaMasterList", withExtension: "pem")
  }

  private static func certificateCount(in url: URL) -> Int {
    guard let contents = try? String(contentsOf: url, encoding: .utf8) else {
      return 0
    }
    return max(0, contents.components(separatedBy: "-----BEGIN CERTIFICATE-----").count - 1)
  }

  private static func isApprovedChileanCSCASubject(_ subject: String) -> Bool {
    let fields = subject.split(separator: ",").map {
      $0.trimmingCharacters(in: .whitespacesAndNewlines)
        .replacingOccurrences(of: " ", with: "")
        .uppercased()
    }
    let normalized = subject
      .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
      .uppercased()
    return fields.contains("C=CL")
      && normalized.contains("SERVICIO DE REGISTRO CIVIL")
  }

  private static func isUnexpiredMRZDate(_ value: String, now: Date = Date()) -> Bool {
    guard value.utf8.count == 6,
          value.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 })
    else { return false }
    let components = Array(value)
    guard
      let year = Int(String(components[0...1])),
      let month = Int(String(components[2...3])),
      let day = Int(String(components[4...5]))
    else { return false }

    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? .current
    guard let expiry = calendar.date(
      from: DateComponents(year: 2000 + year, month: month, day: day)
    ) else { return false }
    return expiry >= calendar.startOfDay(for: now)
  }

  private func beginScan() -> Bool {
    scanLock.lock()
    defer { scanLock.unlock() }
    guard !scanInFlight else { return false }
    scanInFlight = true
    return true
  }

  private func setActiveReader(_ reader: NFCPassportReader.PassportReader) {
    scanLock.lock()
    activeReader = reader
    scanLock.unlock()
  }

  private func endScan() {
    scanLock.lock()
    activeReader = nil
    scanInFlight = false
    scanLock.unlock()
  }
}
