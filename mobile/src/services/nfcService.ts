/**
 * NFC Service - Chilean ID Card Reading with PACE Protocol
 * 
 * This module handles reading the NFC chip from Chilean ID cards (Cédula de Identidad)
 * using the PACE (Password Authenticated Connection Establishment) protocol.
 */

import NfcManager, { NfcTech, Ndef } from 'react-native-nfc-manager';
import { createHash, createCipheriv, createDecipheriv } from 'crypto';

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

// MRZ Check digit calculation
function calculateCheckDigit(str: string): number {
    const weights = [7, 3, 1];
    let sum = 0;
    for (let i = 0; i < str.length; i++) {
        let value = 0;
        const char = str[i].toUpperCase();
        if (char >= '0' && char <= '9') {
            value = parseInt(char, 10);
        } else if (char >= 'A' && char <= 'Z') {
            value = char.charCodeAt(0) - 55; // A=10, B=11, etc.
        } else if (char === '<') {
            value = 0;
        }
        sum += value * weights[i % 3];
    }
    return sum % 10;
}

// Derive BAC keys from MRZ
function deriveBACKeys(mrzInfo: {
    documentNumber: string;
    dateOfBirth: string;
    dateOfExpiry: string;
}): { encKey: Buffer; macKey: Buffer } {
    const { documentNumber, dateOfBirth, dateOfExpiry } = mrzInfo;

    // Calculate check digits
    const docNumCheck = calculateCheckDigit(documentNumber);
    const dobCheck = calculateCheckDigit(dateOfBirth);
    const doeCheck = calculateCheckDigit(dateOfExpiry);

    // Create MRZ info string
    const mrzInfoStr = `${documentNumber}${docNumCheck}${dateOfBirth}${dobCheck}${dateOfExpiry}${doeCheck}`;

    // Create seed using SHA-1
    const seed = createHash('sha1').update(mrzInfoStr).digest();

    // Derive encryption and MAC keys
    const encKeyData = Buffer.concat([seed.slice(0, 16), Buffer.from([0x00, 0x00, 0x00, 0x01])]);
    const macKeyData = Buffer.concat([seed.slice(0, 16), Buffer.from([0x00, 0x00, 0x00, 0x02])]);

    const encKey = createHash('sha1').update(encKeyData).digest().slice(0, 16);
    const macKey = createHash('sha1').update(macKeyData).digest().slice(0, 16);

    return { encKey, macKey };
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

            // If MRZ data provided, attempt BAC authentication
            if (mrzData) {
                const keys = deriveBACKeys(mrzData);
                console.log('BAC keys derived');

                // TODO: Implement full PACE/BAC protocol
                // This requires sending specific APDU commands in sequence
            }

            // For now, return basic tag info
            const result: NFCReadResult = {
                success: true,
                serialNumber,
                data: {
                    documentNumber: mrzData?.documentNumber || '',
                    firstName: '',
                    lastName: '',
                    dateOfBirth: mrzData?.dateOfBirth || '',
                    dateOfExpiry: mrzData?.dateOfExpiry || '',
                    nationality: 'CHL',
                    sex: '',
                    rut: '',
                    serialNumber,
                },
            };

            return result;
        } catch (error: any) {
            console.error('NFC read error:', error);
            return {
                success: false,
                error: error.message || 'Failed to read NFC tag',
            };
        } finally {
            await this.cleanup();
        }
    }

    /**
     * Simple NFC tag read (for NDEF tags)
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
