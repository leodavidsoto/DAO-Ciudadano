/**
 * NFC Service - Chilean ID Card Reading with PACE Protocol
 * 
 * This module handles reading the NFC chip from Chilean ID cards (Cédula de Identidad)
 * using the PACE (Password Authenticated Connection Establishment) protocol.
 */

import NfcManager, { NfcTech, Ndef } from 'react-native-nfc-manager';
import { deriveBACKeys as deriveBACKeysICAO, MRZKeyData } from './bacCrypto';

// APDU Commands for eID reading
const APDU_COMMANDS = {
    SELECT_MF: [0x00, 0xA4, 0x00, 0x0C, 0x02, 0x3F, 0x00],
    SELECT_EF_COM: [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x1E],
    SELECT_EF_SOD: [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x1D],
    SELECT_EF_DG1: [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x01], // MRZ data
    SELECT_EF_DG2: [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x02], // Photo
    SELECT_EF_DG11: [0x00, 0xA4, 0x02, 0x0C, 0x02, 0x01, 0x0B], // Additional details
    READ_BINARY: [0x00, 0xB0, 0x00, 0x00, 0x00],
};

/**
 * Derivación de llaves BAC. Delega en bacCrypto.ts, que está verificado
 * contra los vectores publicados de ICAO 9303 (ver
 * __tests__/bacCrypto.test.ts).
 *
 * La implementación anterior que vivía acá tenía dos errores que la hacían
 * incapaz de autenticar contra un chip real: (1) no rellenaba el número de
 * documento a 9 caracteres con '<' como exige la MRZ, y (2) no ajustaba la
 * paridad impar de las llaves DES. No se notaban porque el protocolo nunca
 * llegaba a ejecutarse.
 */
function deriveBACKeys(mrz: MRZKeyData): { encKey: Buffer; macKey: Buffer } {
    const { kenc, kmac } = deriveBACKeysICAO(mrz);
    return { encKey: kenc, macKey: kmac };
}

export interface ChileanIDData {
    documentNumber: string;
    firstName: string;
    lastName: string;
    dateOfBirth: string;
    dateOfExpiry: string;
    nationality: string;
    sex: string;
    rut: string;
    serialNumber: string;
    photoBase64?: string;
    rawData?: any;
}

export interface NFCReadResult {
    success: boolean;
    data?: ChileanIDData;
    error?: string;
    serialNumber?: string;
    /**
     * true SOLO si se estableció el canal seguro BAC y los datos de
     * identidad vienen firmados por el Registro Civil (EF.SOD verificado).
     *
     * Nunca asumas identidad verificada por `success: true`: leer el número
     * de serie de un tag NFC es "éxito" a nivel de lectura, pero no prueba
     * absolutamente nada sobre quién es la persona.
     */
    identityVerified: boolean;
}

class NFCService {
    private isInitialized = false;

    async initialize(): Promise<boolean> {
        try {
            const supported = await NfcManager.isSupported();
            if (!supported) {
                throw new Error('NFC not supported on this device');
            }

            await NfcManager.start();
            this.isInitialized = true;
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
     * Read Chilean ID card using ISO-DEP (ISO 14443-4)
     * This is the main method for reading the eID chip
     */
    async readChileanID(mrzData?: {
        documentNumber: string;
        dateOfBirth: string;
        dateOfExpiry: string;
    }): Promise<NFCReadResult> {
        try {
            if (!this.isInitialized) {
                await this.initialize();
            }

            // Request NFC technology
            await NfcManager.requestTechnology(NfcTech.IsoDep);

            // Get tag info
            const tag = await NfcManager.getTag();
            const serialNumber = tag?.id || 'unknown';

            console.log('Tag detected:', tag);

            if (!mrzData) {
                return {
                    success: false,
                    identityVerified: false,
                    serialNumber,
                    error:
                        'Faltan los datos de la MRZ (número de documento, fecha de nacimiento y ' +
                        'de expiración). Sin ellos no se pueden derivar las llaves BAC y el chip ' +
                        'no entrega ningún dato.',
                };
            }

            // Las llaves BAC ya se derivan correctamente (bacCrypto.ts,
            // verificado contra los vectores de ICAO 9303). Lo que falta es
            // el intercambio de APDUs sobre el canal seguro.
            deriveBACKeys(mrzData);

            // NO IMPLEMENTADO: autenticación mutua BAC + secure messaging +
            // lectura de DG1/EF.SOD. Hasta que exista, esta función NO puede
            // entregar identidad verificada.
            //
            // Antes devolvía `success: true` con firstName/lastName/rut en
            // blanco, y quien llamaba no tenía forma de distinguir eso de una
            // lectura real. Eso es precisamente la "capacidad fingida" que
            // docs/HANDOFF.md prohíbe, y provocó que el minteo aceptara
            // cualquier tag NFC como si fuera una cédula.
            return {
                success: false,
                identityVerified: false,
                serialNumber,
                error:
                    'La lectura autenticada de la cédula (BAC + DG1/EF.SOD) todavía no está ' +
                    'implementada. Las llaves BAC ya se derivan correctamente; falta el ' +
                    'intercambio de APDUs sobre el canal seguro.',
            };
        } catch (error: any) {
            console.error('NFC read error:', error);
            return {
                success: false,
                identityVerified: false,
                error: error.message || 'Failed to read NFC tag',
            };
        } finally {
            await this.cleanup();
        }
    }

    /**
     * Lectura simple de un tag NDEF.
     *
     * ATENCIÓN: esto lee CUALQUIER tag NFC (una tarjeta de transporte, una
     * llave de hotel) y devuelve su número de serie. NO es lectura de cédula
     * y NO verifica identidad: `identityVerified` siempre es false. Sirve
     * para diagnóstico de hardware NFC, no para registrar a nadie.
     */
    async readSimpleTag(): Promise<NFCReadResult> {
        try {
            if (!this.isInitialized) {
                await this.initialize();
            }

            await NfcManager.requestTechnology(NfcTech.Ndef);

            const tag = await NfcManager.getTag();
            const serialNumber = tag?.id || 'unknown';

            // Try to read NDEF message
            let ndefRecords: any[] = [];
            if (tag?.ndefMessage) {
                ndefRecords = tag.ndefMessage.map((record: any) => {
                    if (record.tnf === Ndef.TNF_WELL_KNOWN) {
                        if (Ndef.isType(record, Ndef.RTD_TEXT)) {
                            return { type: 'text', value: Ndef.text.decodePayload(record.payload) };
                        }
                        if (Ndef.isType(record, Ndef.RTD_URI)) {
                            return { type: 'uri', value: Ndef.uri.decodePayload(record.payload) };
                        }
                    }
                    return { type: 'unknown', value: record };
                });
            }

            return {
                success: true,
                identityVerified: false, // un serial de tag no es identidad
                serialNumber,
                data: {
                    documentNumber: serialNumber,
                    firstName: '',
                    lastName: '',
                    dateOfBirth: '',
                    dateOfExpiry: '',
                    nationality: '',
                    sex: '',
                    rut: '',
                    serialNumber,
                    rawData: ndefRecords,
                },
            };
        } catch (error: any) {
            return {
                success: false,
                identityVerified: false,
                error: error.message || 'Failed to read NFC tag',
            };
        } finally {
            await this.cleanup();
        }
    }

    async cleanup(): Promise<void> {
        try {
            await NfcManager.cancelTechnologyRequest();
        } catch {
            // Ignore cleanup errors
        }
    }

    async stopReading(): Promise<void> {
        await this.cleanup();
    }
}

export const nfcService = new NFCService();
export default nfcService;
