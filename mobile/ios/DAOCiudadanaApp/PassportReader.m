#import <React/RCTBridgeModule.h>

@interface RCT_EXTERN_MODULE(PassportReader, NSObject)

// `aaChallenge`: desafío de Autenticación Activa en base64, emitido por el
// servidor. Cadena vacía = esta lectura no lleva AA. Si esta firma deja de
// coincidir con la de PassportReader.swift, el método no se registra y el
// puente falla en tiempo de ejecución, no de compilación.
RCT_EXTERN_METHOD(startPACESession:(NSString *)can
                  dob:(NSString *)dob
                  doe:(NSString *)doe
                  aaChallenge:(NSString *)aaChallenge
                  withResolver:(RCTPromiseResolveBlock)resolve
                  withRejecter:(RCTPromiseRejectBlock)reject)

RCT_EXTERN_METHOD(cancelPACESession)

@end
