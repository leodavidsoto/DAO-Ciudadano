jest.mock('react-native-quick-crypto', () => require('crypto'));

import { NativeModules } from 'react-native';
import nfcService, {
    isVerifiedNFCReadResult,
    parseNativePassportReadResult,
} from '../nfcService';

const validNativePayload = () => ({
    identityVerified: true,
    data: {
        documentNumber: ' A1234567< ',
        firstName: 'ANA<MARIA',
        lastName: 'PEREZ<GOMEZ',
        dateOfBirth: '900101',
        dateOfExpiry: '300101',
        nationality: 'chl',
        issuingState: ' chl ',
        sex: 'f',
        personalNumber: '',
    },
    verification: {
        passed: true,
        dataGroupHashesMatch: true,
        sodSignatureValid: true,
        certificateChainTrusted: true,
        paceEstablished: true,
        requiredDataGroupsPresent: true,
        issuingStateIsChile: true,
        documentProfileIsIdentityCard: true,
        documentNotExpired: true,
        countrySigningCertificateIsChile: true,
        trustAnchorsInstalled: 3,
        digestAlgorithm: 'SHA-256',
        signatureAlgorithm: 'SHA256withRSA',
        documentSigner: 'CN=Document Signer',
        documentSignerIssuer: 'CN=CSCA Chile',
        countrySigningCertificateSubject:
            'C=CL,O=Servicio de Registro Civil e Identificacion,CN=CSCA Chile',
        failures: [] as string[],
    },
});

type NativePayload = ReturnType<typeof validNativePayload>;

describe('PassportReader runtime boundary', () => {
    afterEach(() => {
        delete (NativeModules as Record<string, unknown>).PassportReader;
        jest.clearAllMocks();
    });

    it('accepts only a complete verified payload and normalizes DG1 fields', () => {
        const result = parseNativePassportReadResult(validNativePayload());

        expect(result.status).toBe('verified');
        expect(isVerifiedNFCReadResult(result)).toBe(true);
        if (result.status !== 'verified') throw new Error('Expected verified fixture');

        expect(result.data).toEqual(expect.objectContaining({
            documentNumber: 'A1234567',
            firstName: 'ANA MARIA',
            lastName: 'PEREZ GOMEZ',
            issuingState: 'CHL',
            nationality: 'CHL',
            sex: 'F',
        }));
        expect(result.verification.trustAnchorsInstalled).toBe(3);
    });

    it('does not require or expose a tag serial or a fabricated RUT', () => {
        const payload = validNativePayload() as NativePayload & {
            data: NativePayload['data'] & { serialNumber?: string; rut?: string };
        };
        payload.data.serialNumber = '04DEADBEEF';
        payload.data.rut = '11.111.111-1';

        const result = parseNativePassportReadResult(payload);
        expect(result.status).toBe('verified');
        if (result.status !== 'verified') throw new Error('Expected verified fixture');

        expect(result.data).not.toHaveProperty('serialNumber');
        expect(result.data).not.toHaveProperty('rut');
    });

    it.each([
        ['native verdict', (payload: NativePayload) => { payload.identityVerified = false; }],
        ['passive-auth verdict', (payload: NativePayload) => { payload.verification.passed = false; }],
        ['data-group hashes', (payload: NativePayload) => { payload.verification.dataGroupHashesMatch = false; }],
        ['SOD signature', (payload: NativePayload) => { payload.verification.sodSignatureValid = false; }],
        ['CSCA chain', (payload: NativePayload) => { payload.verification.certificateChainTrusted = false; }],
        ['PACE-CAN', (payload: NativePayload) => { payload.verification.paceEstablished = false; }],
        ['required DG1/DG2/SOD', (payload: NativePayload) => { payload.verification.requiredDataGroupsPresent = false; }],
        ['installed trust anchors', (payload: NativePayload) => { payload.verification.trustAnchorsInstalled = 0; }],
        ['Chilean issuer', (payload: NativePayload) => { payload.data.issuingState = 'ARG'; }],
        ['native issuer verdict', (payload: NativePayload) => { payload.verification.issuingStateIsChile = false; }],
        ['identity-card profile', (payload: NativePayload) => { payload.verification.documentProfileIsIdentityCard = false; }],
        ['document expiry', (payload: NativePayload) => { payload.verification.documentNotExpired = false; }],
        ['Chilean CSCA', (payload: NativePayload) => { payload.verification.countrySigningCertificateIsChile = false; }],
        ['Document Signer subject', (payload: NativePayload) => { payload.verification.documentSigner = ''; }],
        ['Document Signer issuer', (payload: NativePayload) => { payload.verification.documentSignerIssuer = ''; }],
        ['CSCA subject', (payload: NativePayload) => { payload.verification.countrySigningCertificateSubject = ''; }],
        ['empty failure list', (payload: NativePayload) => { payload.verification.failures = ['firma inválida']; }],
        ['required DG1 fields', (payload: NativePayload) => { payload.data.firstName = ''; }],
    ])('fails closed when %s evidence is invalid', (_label, mutate) => {
        const payload = validNativePayload();
        mutate(payload);

        const result = parseNativePassportReadResult(payload);
        expect(result).toEqual(expect.objectContaining({
            status: 'read_unverified',
            readCompleted: true,
            identityVerified: false,
        }));
        expect(isVerifiedNFCReadResult(result)).toBe(false);
        expect(result).not.toHaveProperty('data');
    });

    it('rejects malformed bridge responses as failed reads', () => {
        expect(parseNativePassportReadResult(null)).toEqual(expect.objectContaining({
            status: 'failed',
            readCompleted: false,
            errorCode: 'E_INVALID_NATIVE_RESPONSE',
        }));

        const malformed = validNativePayload() as unknown as {
            identityVerified: boolean;
            data: unknown;
            verification: { trustAnchorsInstalled: string };
        };
        malformed.verification.trustAnchorsInstalled = '3';
        expect(parseNativePassportReadResult(malformed)).toEqual(expect.objectContaining({
            status: 'failed',
            readCompleted: false,
            errorCode: 'E_INVALID_NATIVE_RESPONSE',
        }));
    });

    it('validates the CAN before invoking the native module', async () => {
        const startPACESession = jest.fn(async () => validNativePayload());
        (NativeModules as Record<string, unknown>).PassportReader = { startPACESession };

        const result = await nfcService.readChileanIDPACE('12A456');
        expect(result).toEqual(expect.objectContaining({
            status: 'failed',
            errorCode: 'E_INVALID_CAN',
        }));
        expect(startPACESession).not.toHaveBeenCalled();
    });

    it('validates the native module shape and its resolved payload', async () => {
        (NativeModules as Record<string, unknown>).PassportReader = {
            startPACESession: 'not-a-function',
        };
        await expect(nfcService.readChileanIDPACE('123456')).resolves.toEqual(
            expect.objectContaining({ status: 'failed', errorCode: 'E_MODULE_UNAVAILABLE' }),
        );

        const startPACESession = jest.fn(async () => validNativePayload());
        (NativeModules as Record<string, unknown>).PassportReader = { startPACESession };
        const result = await nfcService.readChileanIDPACE('123456');

        expect(startPACESession).toHaveBeenCalledWith('123456');
        expect(result.status).toBe('verified');
    });

    it('forwards cancellation to the native CoreNFC owner', async () => {
        const cancelPACESession = jest.fn();
        (NativeModules as Record<string, unknown>).PassportReader = {
            startPACESession: jest.fn(),
            cancelPACESession,
        };

        await nfcService.stopReading();

        expect(cancelPACESession).toHaveBeenCalledTimes(1);
    });

    it('propagates a typed native error without treating it as a read', async () => {
        const startPACESession = jest.fn(async () => {
            throw { code: 'E_PACE_FAILED', message: 'CAN rechazado' };
        });
        (NativeModules as Record<string, unknown>).PassportReader = { startPACESession };

        await expect(nfcService.readChileanIDPACE('123456')).resolves.toEqual({
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            errorCode: 'E_PACE_FAILED',
            error: 'CAN rechazado',
        });
    });
});
