/**
 * NFC Scanner Screen - experimental NDEF tag reader
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Animated,
    Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { TextInput } from 'react-native-gesture-handler';
import nfcService from '../services/nfcService';

interface ScanScreenProps {
    navigation: any;
}

const ScanScreen: React.FC<ScanScreenProps> = ({ navigation }) => {
    const [isScanning, setIsScanning] = useState(false);
    const [nfcEnabled, setNfcEnabled] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [can, setCan] = useState('');
    const pulseAnim = React.useRef(new Animated.Value(1)).current;

    const checkNFCStatus = useCallback(async () => {
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
    }, []);

    const startPulseAnimation = useCallback(() => {
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
    }, [pulseAnim]);

    useEffect(() => {
        checkNFCStatus();
        return () => {
            nfcService.stopReading();
        };
    }, [checkNFCStatus]);

    useEffect(() => {
        if (isScanning) {
            startPulseAnimation();
        } else {
            pulseAnim.setValue(1);
        }
    }, [isScanning, pulseAnim, startPulseAnimation]);

    const handleStartScan = async () => {
        if (!nfcEnabled) {
            Alert.alert('NFC Deshabilitado', 'Por favor habilita NFC primero');
            return;
        }

        setIsScanning(true);
        setError(null);
        try {
            // Intentar leer la cédula usando PACE con el CAN proporcionado.
            // Si el CAN no se provee o es solo modo diagnóstico, se puede usar readSimpleTag().
            const result = can.length === 6 
                ? await nfcService.readChileanIDPACE(can) 
                : await nfcService.readSimpleTag();

            if (result.success && result.data) {
                navigation.navigate('Success', {
                    idData: result.data,
                    serialNumber: result.serialNumber,
                    identityVerified: result.identityVerified,
                });
            } else {
                setError(result.error || 'Error al leer la cédula mediante PACE');
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
                <Text style={styles.title}>PRUEBA DE LECTOR NFC</Text>
                <Text style={styles.subtitle}>
                    Detecta un tag NDEF; no autentica una cédula ni verifica identidad
                </Text>
            </View>

            {/* Scanner Area & CAN Input */}
            <View style={styles.scannerContainer}>
                {!isScanning && (
                    <View style={styles.inputContainer}>
                        <Text style={styles.inputLabel}>Número de Acceso a la Tarjeta (CAN)</Text>
                        <TextInput
                            style={styles.input}
                            placeholder="Ej: 123456"
                            placeholderTextColor="#555"
                            value={can}
                            onChangeText={setCan}
                            keyboardType="number-pad"
                            maxLength={6}
                        />
                        <Text style={styles.inputHint}>Ingresa los 6 dígitos impresos en el frente de tu cédula.</Text>
                    </View>
                )}

                <Animated.View
                    style={[
                        styles.scanCircle,
                        {
                            transform: [{ scale: pulseAnim }],
                            backgroundColor: isScanning ? '#00FFFF30' : '#00FFFF10',
                            borderColor: isScanning ? '#00FFFF' : '#00FFFF50',
                            marginTop: isScanning ? 0 : 20,
                        },
                    ]}
                >
                    <View style={styles.innerCircle}>
                        <Text style={styles.nfcIcon}>📡</Text>
                        <Text style={styles.scanText}>
                            {isScanning ? 'Escaneando PACE...' : 'Listo'}
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
                    2. Acerca un tag NFC compatible a la parte trasera del teléfono
                </Text>
                <Text style={styles.instructionText}>
                    3. Mantén el tag quieto hasta que se complete la lectura
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
        width: '100%',
    },
    inputContainer: {
        width: '80%',
        marginBottom: 20,
    },
    inputLabel: {
        color: '#00FFFF',
        fontSize: 14,
        marginBottom: 8,
    },
    input: {
        backgroundColor: '#0a0a2a',
        borderWidth: 1,
        borderColor: '#00FFFF50',
        borderRadius: 8,
        color: '#FFF',
        fontSize: 24,
        padding: 15,
        textAlign: 'center',
        letterSpacing: 4,
    },
    inputHint: {
        color: '#888',
        fontSize: 12,
        marginTop: 8,
        textAlign: 'center',
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
