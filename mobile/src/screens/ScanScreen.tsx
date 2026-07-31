/**
 * NFC Scanner Screen - Main screen for reading Chilean ID cards
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Animated,
    Platform,
    Alert,
    Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import nfcService, { NFCReadResult, ChileanIDData } from '../services/nfcService';

interface ScanScreenProps {
    navigation: any;
}

const ScanScreen: React.FC<ScanScreenProps> = ({ navigation }) => {
    const [isScanning, setIsScanning] = useState(false);
    const [nfcEnabled, setNfcEnabled] = useState(false);
    const [scanResult, setScanResult] = useState<NFCReadResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const pulseAnim = React.useRef(new Animated.Value(1)).current;

    useEffect(() => {
        checkNFCStatus();
        return () => {
            nfcService.stopReading();
        };
    }, []);

    useEffect(() => {
        if (isScanning) {
            startPulseAnimation();
        } else {
            pulseAnim.setValue(1);
        }
    }, [isScanning]);

    const checkNFCStatus = async () => {
        const initialized = await nfcService.initialize();
        if (initialized) {
            const enabled = await nfcService.isEnabled();
            setNfcEnabled(enabled);
            if (!enabled) {
                Alert.alert(
                    'NFC Deshabilitado',
                    'Por favor habilita NFC en la configuración del dispositivo',
                    [
                        { text: 'Cancelar', style: 'cancel' },
                        { text: 'Abrir Configuración', onPress: () => nfcService.requestEnable() },
                    ]
                );
            }
        }
    };

    const startPulseAnimation = () => {
        Animated.loop(
            Animated.sequence([
                Animated.timing(pulseAnim, {
                    toValue: 1.2,
                    duration: 800,
                    useNativeDriver: true,
                }),
                Animated.timing(pulseAnim, {
                    toValue: 1,
                    duration: 800,
                    useNativeDriver: true,
                }),
            ])
        ).start();
    };

    const handleStartScan = async () => {
        if (!nfcEnabled) {
            Alert.alert('NFC Deshabilitado', 'Por favor habilita NFC primero');
            return;
        }

        setIsScanning(true);
        setError(null);
        setScanResult(null);

        try {
            // OJO: readSimpleTag() lee cualquier tag NFC y NO verifica
            // identidad (identityVerified siempre false). La lectura
            // autenticada de la cédula (BAC sobre DG1/EF.SOD) está en
            // desarrollo; hasta entonces esto sirve para comprobar que el
            // hardware NFC responde, no para registrar a nadie.
            const result = await nfcService.readSimpleTag();

            setScanResult(result);

            if (result.success && result.data) {
                navigation.navigate('Success', {
                    idData: result.data,
                    serialNumber: result.serialNumber,
                    identityVerified: result.identityVerified,
                });
            } else {
                setError(result.error || 'Error al leer la tarjeta');
            }
        } catch (err: any) {
            setError(err.message || 'Error inesperado');
        } finally {
            setIsScanning(false);
        }
    };

    const handleCancelScan = () => {
        nfcService.stopReading();
        setIsScanning(false);
    };

    return (
        <SafeAreaView style={styles.container}>
            {/* Header */}
            <View style={styles.header}>
                <Text style={styles.title}>ESCANEO NFC</Text>
                <Text style={styles.subtitle}>
                    Coloca el chip de tu cédula cerca del teléfono
                </Text>
            </View>

            {/* Scanner Area */}
            <View style={styles.scannerContainer}>
                <Animated.View
                    style={[
                        styles.scanCircle,
                        {
                            transform: [{ scale: pulseAnim }],
                            backgroundColor: isScanning ? '#00FFFF30' : '#00FFFF10',
                            borderColor: isScanning ? '#00FFFF' : '#00FFFF50',
                        },
                    ]}
                >
                    <View style={styles.innerCircle}>
                        <Text style={styles.nfcIcon}>📡</Text>
                        <Text style={styles.scanText}>
                            {isScanning ? 'Escaneando...' : 'Listo para escanear'}
                        </Text>
                    </View>
                </Animated.View>
            </View>

            {/* Instructions */}
            <View style={styles.instructions}>
                <Text style={styles.instructionText}>
                    1. Asegúrate de que NFC esté habilitado
                </Text>
                <Text style={styles.instructionText}>
                    2. Coloca la cédula en la parte trasera del teléfono
                </Text>
                <Text style={styles.instructionText}>
                    3. Mantén quieto hasta que se complete la lectura
                </Text>
            </View>

            {/* Error Display */}
            {error && (
                <View style={styles.errorContainer}>
                    <Text style={styles.errorText}>⚠️ {error}</Text>
                </View>
            )}

            {/* Action Buttons */}
            <View style={styles.buttonContainer}>
                {!isScanning ? (
                    <TouchableOpacity
                        style={[styles.button, !nfcEnabled && styles.buttonDisabled]}
                        onPress={handleStartScan}
                        disabled={!nfcEnabled}
                    >
                        <Text style={styles.buttonText}>INICIAR ESCANEO</Text>
                    </TouchableOpacity>
                ) : (
                    <TouchableOpacity
                        style={[styles.button, styles.cancelButton]}
                        onPress={handleCancelScan}
                    >
                        <Text style={styles.buttonText}>CANCELAR</Text>
                    </TouchableOpacity>
                )}
            </View>

            {/* NFC Status */}
            <View style={styles.statusBar}>
                <View
                    style={[
                        styles.statusIndicator,
                        { backgroundColor: nfcEnabled ? '#00FF00' : '#FF0000' },
                    ]}
                />
                <Text style={styles.statusText}>
                    NFC: {nfcEnabled ? 'Habilitado' : 'Deshabilitado'}
                </Text>
            </View>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#0a0a1a',
    },
    header: {
        padding: 20,
        alignItems: 'center',
    },
    title: {
        fontSize: 24,
        fontWeight: 'bold',
        color: '#00FFFF',
        letterSpacing: 2,
    },
    subtitle: {
        fontSize: 14,
        color: '#888',
        marginTop: 8,
        textAlign: 'center',
    },
    scannerContainer: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
    scanCircle: {
        width: 250,
        height: 250,
        borderRadius: 125,
        borderWidth: 3,
        justifyContent: 'center',
        alignItems: 'center',
    },
    innerCircle: {
        width: 180,
        height: 180,
        borderRadius: 90,
        backgroundColor: '#0a0a1a',
        borderWidth: 2,
        borderColor: '#00FFFF30',
        justifyContent: 'center',
        alignItems: 'center',
    },
    nfcIcon: {
        fontSize: 48,
        marginBottom: 10,
    },
    scanText: {
        color: '#00FFFF',
        fontSize: 14,
        fontWeight: '600',
    },
    instructions: {
        padding: 20,
        backgroundColor: '#0a0a2a',
        marginHorizontal: 20,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#00FFFF20',
    },
    instructionText: {
        color: '#aaa',
        fontSize: 13,
        marginVertical: 4,
    },
    errorContainer: {
        margin: 20,
        padding: 15,
        backgroundColor: '#FF000020',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#FF0000',
    },
    errorText: {
        color: '#FF6666',
        textAlign: 'center',
    },
    buttonContainer: {
        padding: 20,
    },
    button: {
        backgroundColor: '#00FFFF',
        paddingVertical: 16,
        borderRadius: 12,
        alignItems: 'center',
    },
    buttonDisabled: {
        backgroundColor: '#333',
    },
    cancelButton: {
        backgroundColor: '#FF4444',
    },
    buttonText: {
        color: '#000',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    statusBar: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        paddingBottom: 20,
    },
    statusIndicator: {
        width: 10,
        height: 10,
        borderRadius: 5,
        marginRight: 8,
    },
    statusText: {
        color: '#666',
        fontSize: 12,
    },
});

export default ScanScreen;
