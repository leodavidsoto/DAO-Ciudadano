jest.mock('react-native-quick-crypto', () => require('crypto'));

import { NativeModules } from 'react-native';
import nfcService, {
    describeReadFailure,
    isValidCAN,
    isVerifiedNFCReadResult,
    normalizeCAN,
    parseNativePassportReadResult,
    PACE_CAN_MAX_LENGTH,
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
    // Raw chip files, base64 without wrapping. The parser only accepts a
    // reading it could hand to the backend for its own passive authentication.
    files: {
        sod: 'RUYuU09E',
        dg1: 'REcx',
        dg2: 'REcy',
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
        // Sin los archivos en crudo el servidor no puede repetir la
        // Autenticación Pasiva, y un veredicto que solo calculó este teléfono
        // no es evidencia que nadie más pueda comprobar.
        ['raw EF.SOD', (payload: NativePayload) => { payload.files.sod = ''; }],
        ['raw DG1', (payload: NativePayload) => { payload.files.dg1 = ''; }],
        ['raw DG2', (payload: NativePayload) => { payload.files.dg2 = ''; }],
        // Base64 con saltos de línea: el decodificador estricto del backend lo
        // rechazaría, así que la lectura no vale como alta.
        // Longitud múltiplo de 4 a propósito: así lo que falla es el patrón
        // estricto y no el chequeo de longitud.
        ['wrapped base64', (payload: NativePayload) => { payload.files.sod = 'RUYu\nU09EAAA'; }],
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

    // Both native readers require exactly six digits (PassportReaderModule.kt
    // and PassportReader.swift). A JS rule that disagrees makes every scan
    // unreachable, so the contract is pinned on both sides.
    it.each([
        ['12345', 'too few characters'],
        ['A1B2C', 'too few characters with letters'],
        ['1234567890123456', 'more than fifteen characters'],
        ['', 'an empty value'],
    ])('rejects %s (%s) before invoking the native module', async (candidate) => {
        const startPACESession = jest.fn(async () => validNativePayload());
        (NativeModules as Record<string, unknown>).PassportReader = { startPACESession };

        expect(isValidCAN(candidate)).toBe(false);
        const result = await nfcService.readChileanIDPACE(candidate);
        expect(result).toEqual(expect.objectContaining({
            status: 'failed',
            errorCode: 'E_INVALID_CAN',
        }));
        expect(startPACESession).not.toHaveBeenCalled();
    });

    it('agrees with the native alphanumeric document-number contract', () => {
        // El número impreso en la cédula chilena es alfanumérico y de largo
        // variable (p. ej. A12345678), no seis dígitos.
        expect(PACE_CAN_MAX_LENGTH).toBe(15);
        expect(isValidCAN('A12345678')).toBe(true);
        expect(isValidCAN('123456')).toBe(true);
        expect(normalizeCAN(' a12-345 678 ')).toBe('A12345678');
        expect(normalizeCAN('1234567890123456789')).toHaveLength(PACE_CAN_MAX_LENGTH);
    });

    it('validates the native module shape and its resolved payload', async () => {
        (NativeModules as Record<string, unknown>).PassportReader = {
            startPACESession: 'not-a-function',
        };
        await expect(nfcService.readChileanIDPACE('A12345678')).resolves.toEqual(
            expect.objectContaining({ status: 'failed', errorCode: 'E_MODULE_UNAVAILABLE' }),
        );

        const startPACESession = jest.fn(async () => validNativePayload());
        (NativeModules as Record<string, unknown>).PassportReader = { startPACESession };
        const result = await nfcService.readChileanIDPACE('A12345678', '850101', '301231');

        // Las tres partes viajan al nativo: sin fechas no se puede derivar la
        // clave de respaldo cuando la cédula no publica CAN.
        expect(startPACESession).toHaveBeenCalledWith('A12345678', '850101', '301231');
        expect(result.status).toBe('verified');
    });

    it('no longer exposes the NDEF or BAC placeholder reads', () => {
        const surface = nfcService as unknown as Record<string, unknown>;
        expect(surface.readSimpleTag).toBeUndefined();
        expect(surface.readChileanID).toBeUndefined();
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

describe('failure guidance', () => {
    const failed = (errorCode: string, error = 'detalle nativo') =>
        describeReadFailure({
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            errorCode,
            error,
        });

    it.each([
        ['E_INVALID_CAN', 'fix_can'],
        ['E_PACE_FAILED', 'fix_can'],
        ['E_TAG_LOST', 'retry_positioning'],
        ['E_TIMEOUT', 'retry_positioning'],
        ['E_READ_FAILED', 'retry_positioning'],
        ['E_DOCUMENT_READ_FAILED', 'retry_positioning'],
        ['E_TAG_NOT_SUPPORTED', 'retry_positioning'],
        ['E_SCAN_IN_PROGRESS', 'retry_positioning'],
        ['E_NO_ACTIVITY', 'retry_positioning'],
        ['E_NFC_READER_MODE', 'retry_positioning'],
        ['E_NFC_DISABLED', 'enable_nfc'],
        ['E_NFC_UNAVAILABLE', 'unsupported'],
        ['E_PACE_UNSUPPORTED', 'unsupported'],
        ['E_CSCA_MASTER_LIST_MISSING', 'app_defect'],
        ['E_MODULE_UNAVAILABLE', 'app_defect'],
        ['E_INVALID_NATIVE_RESPONSE', 'app_defect'],
    ])('routes %s to the %s action', (code, action) => {
        const guidance = failed(code);
        expect(guidance.action).toBe(action);
        expect(guidance.title).not.toHaveLength(0);
        expect(guidance.detail).not.toHaveLength(0);
    });

    it('never blames the CAN when the card was pulled away mid-read', () => {
        // Visto en un teléfono real: TagLostException leyendo EF.CardAccess,
        // que se lee ANTES de PACE. La clave nunca llegó a probarse, así que
        // mandar al ciudadano a revisar dígitos correctos es un diagnóstico
        // falso.
        const guidance = failed(
            'E_TAG_LOST',
            'IOException -> CardServiceException: Read binary failed on file 11c ' +
                '-> TagLostException: Tag was lost',
        );

        expect(guidance.action).toBe('retry_positioning');
        expect(guidance.action).not.toBe('fix_can');
        expect(`${guidance.title} ${guidance.detail}`).not.toMatch(/revisa los dígitos/i);
        expect(guidance.technicalDetail).toMatch(/TagLostException/);
    });

    it('points a rejected secure channel at the whole key, without asserting the cause', () => {
        const guidance = failed('E_PACE_FAILED', 'PACE rechazado por el chip');

        expect(guidance.action).toBe('fix_can');
        // La clave puede derivarse del documento solo o del documento más las
        // dos fechas. Señalar únicamente el número dejaría al ciudadano
        // corrigiendo un campo correcto cuando el error está en una fecha.
        expect(guidance.detail).toMatch(/número de documento/i);
        expect(guidance.detail).toMatch(/fechas/i);
        // El chip no dice por qué rechazó: no se afirma una causa como hecho.
        expect(guidance.detail).toMatch(/sin decir por qué/i);
        // The native text is preserved separately, never rewritten as a verdict.
        expect(guidance.technicalDetail).toBe('PACE rechazado por el chip');
    });

    it('does not blame the citizen when the build lacks a trust chain', () => {
        expect(failed('E_CSCA_MASTER_LIST_MISSING').detail)
            .toMatch(/no es un problema de tu cédula/i);
    });

    it('treats an unverified read as unusable evidence', () => {
        const guidance = describeReadFailure({
            status: 'read_unverified',
            readCompleted: true,
            identityVerified: false,
            error: 'La firma de EF.SOD no es válida.',
        });

        expect(guidance.action).toBe('app_defect');
        expect(guidance.title).toMatch(/no se verificó/i);
        expect(guidance.technicalDetail).toBe('La firma de EF.SOD no es válida.');
    });

    it('falls back safely for an unknown native code', () => {
        const guidance = failed('E_SOMETHING_NEW');
        expect(guidance.action).toBe('retry_positioning');
        expect(guidance.technicalDetail).toBe('detalle nativo');
    });
});
