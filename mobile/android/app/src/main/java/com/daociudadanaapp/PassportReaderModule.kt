package com.daociudadanaapp

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

class PassportReaderModule(reactContext: ReactApplicationContext) : ReactContextBaseJavaModule(reactContext) {

    override fun getName(): String {
        return "PassportReader"
    }

    @ReactMethod
    fun startPACESession(can: String, promise: Promise) {
        try {
            // TODO (Fase 4.2): 
            // 1. Obtener la instancia del IsoDep
            // 2. Usar JMRTD para establecer la conexión PACE usando el CAN
            // 3. Extraer Data Group 1 (MRZ), Data Group 2 (Foto) y el SOD
            // 4. Validar la firma del SOD (Active Authentication o Passive Authentication con CSCA)
            
            // Retornamos un mock indicando que falta implementación criptográfica
            promise.reject("E_NOT_IMPLEMENTED", "PACE handshake with JMRTD is not yet implemented.")
        } catch (e: Exception) {
            promise.reject("E_PACE_FAILED", e.message)
        }
    }
}
