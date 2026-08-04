#import <React/RCTBridgeModule.h>

@interface RCT_EXTERN_MODULE(PassportReader, NSObject)

RCT_EXTERN_METHOD(startPACESession:(NSString *)can
                  withResolver:(RCTPromiseResolveBlock)resolve
                  withRejecter:(RCTPromiseRejectBlock)reject)

RCT_EXTERN_METHOD(cancelPACESession)

@end
