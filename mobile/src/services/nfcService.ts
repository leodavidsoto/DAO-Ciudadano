/**
 * NFC service for the mobile pilot.
 *
 * The native PassportReader owns the authenticated PACE/passive-auth flow.
 * This file is the runtime trust boundary: a resolved native promise only
 * means that a read completed. Identity is verified only after every required
 * piece of evidence has been validated again in JavaScript.
 */

import { NativeModules } from 'react-native';
import NfcManager from 'react-native-nfc-manager';

type UnknownRecord = Record<string, unknown>;

/**
 * The Card Access Number is the six printed digits that key PACE. It is not
 * the document number and not the tag serial: both native readers reject
 * anything that is not exactly six ASCII digits, so this layer must agree.
 */
export const PACE_CAN_LENGTH = 6;
const CAN_PATTERN = /^[0-9]{6}$/;

/** Normalizes user input before it reaches the CAN validator. */
export function normalizeCAN(value: string): string {
    return value.replace(/[^0-9]/g, '').slice(0, PACE_CAN_LENGTH);
}

export function isValidCAN(value: string): boolean {
    return CAN_PATTERN.test(value);
}

interface NativePassportReaderModule {
    startPACESession(can: string): Promise<unknown>;
    cancelPACESession?: () => void;
}

export interface PassportPhoto {
    available: boolean;
    mimeType?: string;
    base64?: string;
    reason?: string;
}

/** Authenticated fields read from DG1 (and optionally DG2). */
export interface ChileanIDData {
    documentNumber: string;
    firstName: string;
    lastName: string;
    dateOfBirth: string;
    dateOfExpiry: string;
    nationality: string;
    issuingState: string;
    sex: string;
    personalNumber?: string;
    optionalData1?: string;
    optionalData2?: string;
    photo?: PassportPhoto;
}

/** Passive-auth evidence returned by the native module (ADR-004). */
export interface PassiveAuthResult {
    passed: boolean;
    dataGroupHashesMatch: boolean;
    sodSignatureValid: boolean;
    certificateChainTrusted: boolean;
    paceEstablished: boolean;
    requiredDataGroupsPresent: boolean;
    issuingStateIsChile: boolean;
    documentProfileIsIdentityCard: boolean;
    documentNotExpired: boolean;
    countrySigningCertificateIsChile: boolean;
    trustAnchorsInstalled: number;
    digestAlgorithm?: string;
    signatureAlgorithm?: string;
    documentSigner?: string;
    documentSignerIssuer?: string;
    countrySigningCertificateSubject?: string;
    failures: string[];
}

export interface VerifiedPassiveAuthResult extends PassiveAuthResult {
    passed: true;
    dataGroupHashesMatch: true;
    sodSignatureValid: true;
    certificateChainTrusted: true;
    paceEstablished: true;
    requiredDataGroupsPresent: true;
    issuingStateIsChile: true;
    documentProfileIsIdentityCard: true;
    documentNotExpired: true;
    countrySigningCertificateIsChile: true;
}

export interface VerifiedNFCReadResult {
    status: 'verified';
    readCompleted: true;
    identityVerified: true;
    data: ChileanIDData;
    verification: VerifiedPassiveAuthResult;
}

export interface UnverifiedNFCReadResult {
    status: 'read_unverified';
    readCompleted: true;
    identityVerified: false;
    error: string;
    verification?: PassiveAuthResult;
}

export interface FailedNFCReadResult {
    status: 'failed';
    readCompleted: false;
    identityVerified: false;
    error: string;
    errorCode?: string;
}

export type NFCReadResult =
    | VerifiedNFCReadResult
    | UnverifiedNFCReadResult
    | FailedNFCReadResult;

function isRecord(value: unknown): value is UnknownRecord {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizedRequiredString(value: unknown): string | null {
    if (typeof value !== 'string') return null;

    const normalized = value.trim();
    if (!normalized || /^(?:<|\?|unknown)+$/i.test(normalized)) return null;
    return normalized;
}

function normalizedMrzName(value: unknown): string | null {
    const normalized = normalizedRequiredString(value);
    if (!normalized) return null;

    const withoutFillers = normalized.replace(/</g, ' ').replace(/\s+/g, ' ').trim();
    return withoutFillers || null;
}

function normalizedMrzCode(value: unknown): string | null {
    const normalized = normalizedRequiredString(value);
    if (!normalized) return null;

    const withoutFillers = normalized.replace(/<+$/g, '').trim().toUpperCase();
    return withoutFillers || null;
}

function normalizedOptionalString(value: unknown): string | undefined {
    if (typeof value !== 'string') return undefined;
    const normalized = value.replace(/<+$/g, '').trim();
    return normalized || undefined;
}

function parsePassportPhoto(value: unknown): PassportPhoto | undefined {
    if (!isRecord(value) || typeof value.available !== 'boolean') return undefined;

    return {
        available: value.available,
        mimeType: normalizedOptionalString(value.mimeType),
        base64: normalizedOptionalString(value.base64),
        reason: normalizedOptionalString(value.reason),
    };
}

function parseChileanIDData(value: unknown): ChileanIDData | null {
    if (!isRecord(value)) return null;

    const documentNumber = normalizedMrzCode(value.documentNumber);
    const firstName = normalizedMrzName(value.firstName);
    const lastName = normalizedMrzName(value.lastName);
    const dateOfBirth = normalizedRequiredString(value.dateOfBirth);
    const dateOfExpiry = normalizedRequiredString(value.dateOfExpiry);
    const nationality = normalizedMrzCode(value.nationality);
    const issuingState = normalizedMrzCode(value.issuingState);
    const sex = normalizedMrzCode(value.sex);

    if (
        !documentNumber ||
        !firstName ||
        !lastName ||
        !dateOfBirth ||
        !dateOfExpiry ||
        !nationality ||
        !issuingState ||
        !sex ||
        !/^\d{6}$/.test(dateOfBirth) ||
        !/^\d{6}$/.test(dateOfExpiry)
    ) {
        return null;
    }

    return {
        documentNumber,
        firstName,
        lastName,
        dateOfBirth,
        dateOfExpiry,
        nationality,
        issuingState,
        sex,
        personalNumber: normalizedOptionalString(value.personalNumber),
        optionalData1: normalizedOptionalString(value.optionalData1),
        optionalData2: normalizedOptionalString(value.optionalData2),
        photo: parsePassportPhoto(value.photo),
    };
}

function parsePassiveAuthResult(value: unknown): PassiveAuthResult | null {
    if (!isRecord(value)) return null;

    const booleanFields = [
        value.passed,
        value.dataGroupHashesMatch,
        value.sodSignatureValid,
        value.certificateChainTrusted,
        value.paceEstablished,
        value.requiredDataGroupsPresent,
        value.issuingStateIsChile,
        value.documentProfileIsIdentityCard,
        value.documentNotExpired,
        value.countrySigningCertificateIsChile,
    ];
    const failures = value.failures;
    const anchors = value.trustAnchorsInstalled;

    if (
        booleanFields.some(field => typeof field !== 'boolean') ||
        !Number.isInteger(anchors) ||
        (anchors as number) < 0 ||
        !Array.isArray(failures) ||
        failures.some(failure => typeof failure !== 'string')
    ) {
        return null;
    }

    return {
        passed: value.passed as boolean,
        dataGroupHashesMatch: value.dataGroupHashesMatch as boolean,
        sodSignatureValid: value.sodSignatureValid as boolean,
        certificateChainTrusted: value.certificateChainTrusted as boolean,
        paceEstablished: value.paceEstablished as boolean,
        requiredDataGroupsPresent: value.requiredDataGroupsPresent as boolean,
        issuingStateIsChile: value.issuingStateIsChile as boolean,
        documentProfileIsIdentityCard: value.documentProfileIsIdentityCard as boolean,
        documentNotExpired: value.documentNotExpired as boolean,
        countrySigningCertificateIsChile:
            value.countrySigningCertificateIsChile as boolean,
        trustAnchorsInstalled: anchors as number,
        digestAlgorithm: normalizedOptionalString(value.digestAlgorithm),
        signatureAlgorithm: normalizedOptionalString(value.signatureAlgorithm),
        documentSigner: normalizedOptionalString(value.documentSigner),
        documentSignerIssuer: normalizedOptionalString(value.documentSignerIssuer),
        countrySigningCertificateSubject:
            normalizedOptionalString(value.countrySigningCertificateSubject),
        failures: [...(failures as string[])],
    };
}

function requiredEvidenceFailures(
    nativeIdentityVerified: boolean,
    data: ChileanIDData | null,
    verification: PassiveAuthResult | null,
): string[] {
    const failures: string[] = [];

    if (!nativeIdentityVerified) failures.push('El módulo nativo no verificó la identidad.');
    if (!data) failures.push('Faltan campos obligatorios autenticados de DG1.');
    if (data && data.issuingState !== 'CHL') {
        failures.push('El documento no declara a Chile como Estado emisor.');
    }
    if (!verification) {
        failures.push('Falta evidencia estructurada de autenticación pasiva.');
        return failures;
    }

    if (!verification.passed) failures.push('La autenticación pasiva no aprobó.');
    if (!verification.dataGroupHashesMatch) {
        failures.push('Los hashes de los data groups no coinciden con EF.SOD.');
    }
    if (!verification.sodSignatureValid) failures.push('La firma de EF.SOD no es válida.');
    if (!verification.certificateChainTrusted) {
        failures.push('La cadena del Document Signer no llega a una CSCA confiable.');
    }
    if (!verification.paceEstablished) {
        failures.push('PACE-CAN no se estableció; no se admite fallback BAC.');
    }
    if (!verification.requiredDataGroupsPresent) {
        failures.push('La lectura no contiene DG1, DG2 y EF.SOD completos.');
    }
    if (verification.trustAnchorsInstalled <= 0) {
        failures.push('La aplicación no tiene anclas CSCA instaladas.');
    }
    if (!verification.issuingStateIsChile) {
        failures.push('La verificación nativa rechazó el Estado emisor.');
    }
    if (!verification.documentProfileIsIdentityCard) {
        failures.push('El chip no declara un perfil de cédula admitido.');
    }
    if (!verification.documentNotExpired) {
        failures.push('La cédula está vencida o su expiración no es válida.');
    }
    if (!verification.countrySigningCertificateIsChile) {
        failures.push('La cadena no termina en una CSCA chilena aprobada.');
    }
    if (!verification.documentSigner || !verification.documentSignerIssuer) {
        failures.push('Falta evidencia del certificado Document Signer.');
    }
    if (!verification.countrySigningCertificateSubject) {
        failures.push('Falta evidencia de la CSCA que ancló la cadena.');
    }
    if (verification.failures.length > 0) failures.push(...verification.failures);

    return failures;
}

function asVerifiedPassiveAuth(
    verification: PassiveAuthResult,
): VerifiedPassiveAuthResult {
    return {
        ...verification,
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
    };
}

/**
 * Normalizes and validates the untyped React Native bridge payload.
 * Untrusted identity fields are intentionally discarded when verification
 * fails, even if the chip read itself completed.
 */
export function parseNativePassportReadResult(value: unknown): NFCReadResult {
    if (
        !isRecord(value) ||
        typeof value.identityVerified !== 'boolean' ||
        !isRecord(value.data) ||
        !isRecord(value.verification)
    ) {
        return {
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            error: 'PassportReader devolvió una respuesta inválida.',
            errorCode: 'E_INVALID_NATIVE_RESPONSE',
        };
    }

    const nativeIdentityVerified = value.identityVerified;
    const data = parseChileanIDData(value.data);
    const verification = parsePassiveAuthResult(value.verification);
    if (!verification) {
        return {
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            error: 'PassportReader devolvió evidencia con un formato inválido.',
            errorCode: 'E_INVALID_NATIVE_RESPONSE',
        };
    }
    const evidenceFailures = requiredEvidenceFailures(
        nativeIdentityVerified,
        data,
        verification,
    );

    if (data && evidenceFailures.length === 0) {
        return {
            status: 'verified',
            readCompleted: true,
            identityVerified: true,
            data,
            verification: asVerifiedPassiveAuth(verification),
        };
    }

    return {
        status: 'read_unverified',
        readCompleted: true,
        identityVerified: false,
        verification,
        error: `La cédula fue leída, pero no se verificó su identidad. ${evidenceFailures.join(' ')}`,
    };
}

/** Runtime guard used again at the navigation boundary. */
export function isVerifiedNFCReadResult(value: unknown): value is VerifiedNFCReadResult {
    if (!isRecord(value)) return false;
    if (
        value.status !== 'verified' ||
        value.readCompleted !== true ||
        value.identityVerified !== true
    ) {
        return false;
    }

    const data = parseChileanIDData(value.data);
    const verification = parsePassiveAuthResult(value.verification);
    return requiredEvidenceFailures(true, data, verification).length === 0;
}

/** What the citizen can actually do about a failure. */
export type NFCFailureAction = 'fix_can' | 'enable_nfc' | 'retry_positioning' | 'unsupported' | 'app_defect';

export interface NFCFailureGuidance {
    title: string;
    detail: string;
    action: NFCFailureAction;
    /** Raw native text, kept separate so guidance never invents a cause. */
    technicalDetail?: string;
}

/**
 * Maps the native error surface to guidance.
 *
 * Codes come from `PassportReaderModule.kt` (Android) and
 * `PassportReader.swift` (iOS). A chip that refuses PACE cannot tell us *why*,
 * so a wrong CAN is offered as the likely cause, never asserted as fact.
 */
export function describeReadFailure(
    result: FailedNFCReadResult | UnverifiedNFCReadResult,
): NFCFailureGuidance {
    const technicalDetail = result.error?.trim() || undefined;
    const code = result.status === 'failed' ? result.errorCode : undefined;

    switch (code) {
        case 'E_INVALID_CAN':
            return {
                title: 'Ese CAN no tiene el formato correcto',
                detail: `El CAN son exactamente ${PACE_CAN_LENGTH} dígitos impresos en tu cédula. No es el RUT ni el número de documento.`,
                action: 'fix_can',
            };
        case 'E_PACE_FAILED':
            return {
                title: 'No se pudo abrir el canal seguro',
                detail:
                    'La causa más frecuente es un CAN equivocado: el chip rechaza la clave sin decir por qué. ' +
                    'Revisa los dígitos y vuelve a intentarlo sin mover la cédula.',
                action: 'fix_can',
                technicalDetail,
            };
        case 'E_TIMEOUT':
            return {
                title: 'No se detectó ninguna cédula',
                detail:
                    'Apoya la cédula contra la parte trasera del teléfono y mantenla quieta. ' +
                    'Las fundas gruesas y las carcasas metálicas bloquean la lectura.',
                action: 'retry_positioning',
                technicalDetail,
            };
        case 'E_READ_FAILED':
        case 'E_DOCUMENT_READ_FAILED':
            return {
                title: 'La lectura se interrumpió',
                detail:
                    'El canal seguro se abrió, pero la cédula se movió antes de terminar. ' +
                    'Mantenla apoyada sin moverla hasta que el proceso finalice.',
                action: 'retry_positioning',
                technicalDetail,
            };
        case 'E_NFC_DISABLED':
            return {
                title: 'El NFC está apagado',
                detail: 'Actívalo en los ajustes del sistema para poder leer el chip de la cédula.',
                action: 'enable_nfc',
                technicalDetail,
            };
        case 'E_NFC_UNAVAILABLE':
            return {
                title: 'Este dispositivo no puede leer la cédula',
                detail: 'No tiene NFC compatible con documentos de identidad electrónicos.',
                action: 'unsupported',
                technicalDetail,
            };
        case 'E_TAG_NOT_SUPPORTED':
            return {
                title: 'Ese chip no es una cédula legible',
                detail:
                    'El chip detectado no responde a ISO-DEP. Retira otras tarjetas con NFC ' +
                    '(bancarias, de transporte) y acerca solo la cédula.',
                action: 'retry_positioning',
                technicalDetail,
            };
        case 'E_PACE_UNSUPPORTED':
            return {
                title: 'La cédula no publica parámetros PACE',
                detail:
                    'Este documento no admite el canal seguro que exigimos. No se acepta el ' +
                    'respaldo BAC, así que no podemos verificarlo.',
                action: 'unsupported',
                technicalDetail,
            };
        case 'E_SCAN_IN_PROGRESS':
            return {
                title: 'Ya hay una lectura en curso',
                detail: 'Espera a que termine o cancélala antes de iniciar otra.',
                action: 'retry_positioning',
                technicalDetail,
            };
        case 'E_NO_ACTIVITY':
        case 'E_NFC_READER_MODE':
            return {
                title: 'No se pudo activar el lector',
                detail: 'Mantén la app abierta y en primer plano durante toda la lectura.',
                action: 'retry_positioning',
                technicalDetail,
            };
        case 'E_CSCA_MASTER_LIST_MISSING':
        case 'E_MODULE_UNAVAILABLE':
        case 'E_INVALID_NATIVE_RESPONSE':
            return {
                title: 'Esta versión de la app no puede verificar cédulas',
                detail:
                    'Falta la cadena de confianza o el módulo de lectura en este build. ' +
                    'No es un problema de tu cédula: repórtalo al equipo.',
                action: 'app_defect',
                technicalDetail,
            };
        default:
            break;
    }

    if (result.status === 'read_unverified') {
        return {
            title: 'La cédula se leyó, pero no se verificó',
            detail:
                'El chip respondió, pero la evidencia criptográfica no aprobó. ' +
                'No se emite ninguna credencial con una lectura sin verificar.',
            action: 'app_defect',
            technicalDetail,
        };
    }

    return {
        title: 'No se pudo leer la cédula',
        detail: 'Vuelve a intentarlo apoyando la cédula contra la parte trasera del teléfono.',
        action: 'retry_positioning',
        technicalDetail,
    };
}

function getPassportReader(): NativePassportReaderModule | null {
    const candidate: unknown = NativeModules.PassportReader;
    if (!isRecord(candidate) || typeof candidate.startPACESession !== 'function') return null;
    return candidate as unknown as NativePassportReaderModule;
}

function describeNativeError(error: unknown): { error: string; errorCode?: string } {
    if (!isRecord(error)) return { error: 'No se pudo leer la cédula.' };
    return {
        error:
            typeof error.message === 'string' && error.message.trim()
                ? error.message
                : 'No se pudo leer la cédula.',
        errorCode:
            typeof error.code === 'string' && error.code.trim() ? error.code : undefined,
    };
}

class NFCService {
    /**
     * Only powers the NFC availability indicator. The reader session itself
     * is opened by the native module, not by NfcManager.
     */
    async initialize(): Promise<boolean> {
        try {
            const supported = await NfcManager.isSupported();
            if (!supported) throw new Error('NFC not supported on this device');

            await NfcManager.start();
            return true;
        } catch (error) {
            console.error('NFC initialization error:', error);
            return false;
        }
    }

    async isEnabled(): Promise<boolean> {
        try {
            return await NfcManager.isEnabled();
        } catch {
            return false;
        }
    }

    async requestEnable(): Promise<void> {
        await NfcManager.goToNfcSetting();
    }

    /**
     * Reads and verifies a Chilean identity document through native PACE.
     *
     * The ISO-DEP/APDU exchange, the PACE-CAN handshake and passive
     * authentication all live in the native readers (JMRTD on Android,
     * NFCPassportReader on iOS): they own the CSCA trust store, and a
     * JavaScript reimplementation could not validate the EF.SOD chain.
     */
    async readChileanIDPACE(can: string): Promise<NFCReadResult> {
        if (!isValidCAN(can.trim())) {
            return {
                status: 'failed',
                readCompleted: false,
                identityVerified: false,
                errorCode: 'E_INVALID_CAN',
                error: `El CAN debe contener exactamente ${PACE_CAN_LENGTH} dígitos.`,
            };
        }

        const passportReader = getPassportReader();
        if (!passportReader) {
            return {
                status: 'failed',
                readCompleted: false,
                identityVerified: false,
                errorCode: 'E_MODULE_UNAVAILABLE',
                error: 'El módulo nativo PassportReader no está disponible en este build.',
            };
        }

        try {
            const nativeResult = await passportReader.startPACESession(can.trim());
            return parseNativePassportReadResult(nativeResult);
        } catch (error) {
            return {
                status: 'failed',
                readCompleted: false,
                identityVerified: false,
                ...describeNativeError(error),
            };
        }
    }

    async stopReading(): Promise<void> {
        try {
            getPassportReader()?.cancelPACESession?.();
        } catch {
            // The native read promise will still be ignored by ScanScreen's
            // attempt token; cancellation is best-effort at this boundary.
        }
    }
}

export const nfcService = new NFCService();
export default nfcService;
