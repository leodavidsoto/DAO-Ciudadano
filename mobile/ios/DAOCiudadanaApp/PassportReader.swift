import Foundation
import CoreNFC

@objc(PassportReader)
class PassportReader: NSObject {

  @objc(startPACESession:withResolver:withRejecter:)
  func startPACESession(can: String, resolve: @escaping RCTPromiseResolveBlock, reject: @escaping RCTPromiseRejectBlock) {
    // TODO (Fase 4.2): 
    // 1. Iniciar NFCTagReaderSession
    // 2. Usar NFCPassportReader para establecer conexión PACE con el CAN
    // 3. Extraer Data Group 1 (MRZ), Data Group 2 (Foto) y el SOD
    // 4. Validar la firma del SOD (Active Authentication o Passive Authentication con CSCA)
    
    // Retornamos un mock indicando que falta implementación criptográfica
    let error = NSError(domain: "PassportReader", code: 501, userInfo: [NSLocalizedDescriptionKey: "PACE handshake with NFCPassportReader is not yet implemented."])
    reject("E_NOT_IMPLEMENTED", "PACE handshake is not yet implemented.", error)
  }

  @objc
  static func requiresMainQueueSetup() -> Bool {
    return false
  }
}
