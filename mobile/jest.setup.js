/* global jest */

jest.mock('react-native-nfc-manager', () => ({
  __esModule: true,
  default: {
    isSupported: jest.fn(async () => false),
    start: jest.fn(async () => undefined),
    isEnabled: jest.fn(async () => false),
    goToNfcSetting: jest.fn(async () => undefined),
    requestTechnology: jest.fn(async () => undefined),
    getTag: jest.fn(async () => null),
    cancelTechnologyRequest: jest.fn(async () => undefined),
  },
  NfcTech: { Ndef: 'Ndef', IsoDep: 'IsoDep' },
  Ndef: {
    TNF_WELL_KNOWN: 1,
    RTD_TEXT: 'T',
    RTD_URI: 'U',
    isType: jest.fn(() => false),
    text: { decodePayload: jest.fn(() => '') },
    uri: { decodePayload: jest.fn(() => '') },
  },
}));

jest.mock('react-native-keychain', () => ({
  ACCESSIBLE: { WHEN_UNLOCKED_THIS_DEVICE_ONLY: 'WHEN_UNLOCKED_THIS_DEVICE_ONLY' },
  setGenericPassword: jest.fn(async () => true),
  getGenericPassword: jest.fn(async () => false),
  resetGenericPassword: jest.fn(async () => true),
}));
