/**
 * useNFC Hook - Web NFC API Integration
 * Supports reading NFC tags on Chrome for Android
 * 
 * IMPORTANT: Web NFC only works on:
 * - Chrome 89+ on Android
 * - Secure context (HTTPS)
 * - NDEF formatted tags only (not encrypted ID card chips)
 */
import { useState, useCallback, useEffect } from 'react';

const useNFC = () => {
    const [isSupported, setIsSupported] = useState(false);
    const [isReading, setIsReading] = useState(false);
    const [error, setError] = useState(null);
    const [tagData, setTagData] = useState(null);
    const [permission, setPermission] = useState('unknown');

    // Check if Web NFC is supported
    useEffect(() => {
        const checkSupport = () => {
            if ('NDEFReader' in window) {
                setIsSupported(true);
            } else {
                setIsSupported(false);
                setError('Web NFC no está soportado en este navegador. Usa Chrome en Android.');
            }
        };
        checkSupport();
    }, []);

    // Start reading NFC tags
    const startReading = useCallback(async () => {
        if (!isSupported) {
            setError('Web NFC no está soportado');
            return { ok: false, error: 'NFC not supported' };
        }

        setIsReading(true);
        setError(null);
        setTagData(null);

        try {
            // Request NFC permission
            const ndef = new window.NDEFReader();

            await ndef.scan();
            setPermission('granted');

            // Set up event listeners
            ndef.addEventListener('reading', ({ message, serialNumber }) => {
                console.log('NFC Tag detected:', { serialNumber, message });

                const records = [];
                for (const record of message.records) {
                    records.push({
                        recordType: record.recordType,
                        mediaType: record.mediaType,
                        data: decodeNDEFRecord(record),
                    });
                }

                const data = {
                    serialNumber: serialNumber || generateSerialFromRecords(records),
                    timestamp: new Date().toISOString(),
                    records,
                    raw: message,
                };

                setTagData(data);
                setIsReading(false);
            });

            ndef.addEventListener('readingerror', (event) => {
                console.error('NFC read error:', event);
                setError('Error al leer la etiqueta NFC. Asegúrate de mantener el dispositivo cerca.');
                setIsReading(false);
            });

            return { ok: true, message: 'Scanning started' };
        } catch (err) {
            console.error('NFC Error:', err);

            let errorMessage = 'Error al acceder al NFC';
            if (err.name === 'NotAllowedError') {
                errorMessage = 'Permiso de NFC denegado. Habilita NFC en configuración.';
                setPermission('denied');
            } else if (err.name === 'NotSupportedError') {
                errorMessage = 'NFC no soportado en este dispositivo.';
            } else if (err.name === 'AbortError') {
                errorMessage = 'Lectura NFC cancelada.';
            } else {
                errorMessage = err.message || 'Error desconocido al leer NFC';
            }

            setError(errorMessage);
            setIsReading(false);
            return { ok: false, error: errorMessage };
        }
    }, [isSupported]);

    // Stop reading (cleanup)
    const stopReading = useCallback(() => {
        setIsReading(false);
    }, []);

    // Write to NFC tag (for future use)
    const writeTag = useCallback(async (data) => {
        if (!isSupported) {
            return { ok: false, error: 'NFC not supported' };
        }

        try {
            const ndef = new window.NDEFReader();
            await ndef.write(data);
            return { ok: true };
        } catch (err) {
            console.error('NFC Write Error:', err);
            return { ok: false, error: err.message };
        }
    }, [isSupported]);

    return {
        // State
        isSupported,
        isReading,
        error,
        tagData,
        permission,

        // Actions
        startReading,
        stopReading,
        writeTag,

        // Computed
        hasData: !!tagData,
        serialNumber: tagData?.serialNumber,
    };
};

// Helper function to decode NDEF records
function decodeNDEFRecord(record) {
    try {
        if (record.recordType === 'text') {
            const decoder = new TextDecoder(record.encoding || 'utf-8');
            return decoder.decode(record.data);
        }
        if (record.recordType === 'url') {
            const decoder = new TextDecoder();
            return decoder.decode(record.data);
        }
        if (record.data) {
            // Return as hex string for binary data
            const bytes = new Uint8Array(record.data.buffer || record.data);
            return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
        }
        return null;
    } catch (e) {
        console.error('Error decoding record:', e);
        return null;
    }
}

// Generate serial number from record data if not available
function generateSerialFromRecords(records) {
    const data = records.map(r => r.data).join('');
    let hash = 0;
    for (let i = 0; i < data.length; i++) {
        const char = data.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash).toString(16).toUpperCase().padStart(8, '0');
}

export default useNFC;
