/** NFC scanner for authenticated Chilean identity documents. */

import React, { useState, useEffect, useCallback } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Animated,
    Alert,
    TextInput,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import nfcService, { isVerifiedNFCReadResult } from '../services/nfcService';
import { theme } from '../styles/theme';

interface ScanScreenProps {
    navigation: any;
}

const ScanScreen: React.FC<ScanScreenProps> = ({ navigation }) => {
    const [isScanning, setIsScanning] = useState(false);
    const [nfcEnabled, setNfcEnabled] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [can, setCan] = useState('');
    const pulseAnim = React.useRef(new Animated.Value(1)).current;
    const scanAttempt = React.useRef(0);

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
            scanAttempt.current += 1;
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
        const normalizedCan = can.trim().toUpperCase();
        if (!/^[A-Z0-9]{9}$/.test(normalizedCan)) {
            setError('El CAN debe contener exactamente los 9 caracteres impresos en la cédula.');
            return;
        }

        if (!nfcEnabled) {
            Alert.alert('NFC Deshabilitado', 'Por favor habilita NFC primero');
            return;
        }

        setIsScanning(true);
        setError(null);
        const attempt = ++scanAttempt.current;
        try {
            const result = await nfcService.readChileanIDPACE(normalizedCan);
            if (attempt !== scanAttempt.current) return;

            if (isVerifiedNFCReadResult(result)) {
                navigation.navigate('Success', { result });
            } else {
                setError(result.error || 'Error al leer la cédula mediante PACE');
            }
        } catch (err: any) {
            if (attempt === scanAttempt.current) {
                setError(err.message || 'Error inesperado');
            }
        } finally {
            if (attempt === scanAttempt.current) setIsScanning(false);
        }
    };

    const handleCancelScan = () => {
        scanAttempt.current += 1;
        nfcService.stopReading();
        setIsScanning(false);
    };

    return (
        <SafeAreaView style={styles.container}>
            {/* Header */}
            <View style={styles.header}>
                <Text style={styles.title}>LECTURA eMRTD</Text>
                <Text style={styles.subtitle}>
                    Escanea el chip NFC para comprobar sus datos firmados y la cadena documental instalada.
                </Text>
            </View>

            {/* Scanner Area & CAN Input */}
            <View style={styles.scannerContainer}>
                {!isScanning && (
                    <View style={styles.inputContainer}>
                        <Text style={styles.inputLabel}>Número de Documento (CAN)</Text>
                        <TextInput
                            style={styles.input}
                            placeholder="Ej: 123456789"
                            placeholderTextColor="#555"
                            value={can}
                            onChangeText={setCan}
                            keyboardType="default"
                            autoCapitalize="characters"
                            maxLength={9}
                        />
                        <Text style={styles.inputHint}>Ingresa los 9 caracteres impresos en el frente de tu cédula.</Text>
                    </View>
                )}

                <Animated.View
                    style={[
                        styles.scanCircle,
                        {
                            transform: [{ scale: pulseAnim }],
                            backgroundColor: isScanning ? theme.colors.primarySoft : '#FFFFFF',
                            borderColor: isScanning ? theme.colors.primary : theme.colors.borderDark,
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
                    2. Acerca tu cédula a la parte trasera del teléfono
                </Text>
                <Text style={styles.instructionText}>
                    3. Mantenla quieta hasta que finalice PACE y la autenticación pasiva
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
                        { backgroundColor: nfcEnabled ? theme.colors.success : theme.colors.danger },
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
        backgroundColor: theme.colors.background,
    },
    header: {
        padding: 20,
        alignItems: 'center',
    },
    title: {
        ...theme.typography.title,
        letterSpacing: 0,
    },
    subtitle: {
        ...theme.typography.caption,
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
        ...theme.typography.body,
        fontWeight: 'bold',
        marginBottom: 8,
    },
    input: {
        backgroundColor: theme.colors.surface,
        borderWidth: 1,
        borderColor: theme.colors.borderDark,
        borderRadius: theme.radius.sm,
        color: theme.colors.ink,
        fontSize: 24,
        padding: 15,
        textAlign: 'center',
        letterSpacing: 4,
    },
    inputHint: {
        ...theme.typography.caption,
        marginTop: 8,
        textAlign: 'center',
    },
    scanCircle: {
        width: 180,
        height: 180,
        borderRadius: 90,
        borderWidth: 2,
        justifyContent: 'center',
        alignItems: 'center',
    },
    innerCircle: {
        width: 130,
        height: 130,
        borderRadius: 65,
        backgroundColor: theme.colors.surface,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        justifyContent: 'center',
        alignItems: 'center',
        ...theme.shadows.light,
    },
    nfcIcon: {
        fontSize: 36,
        marginBottom: 10,
    },
    scanText: {
        color: theme.colors.primary,
        fontSize: 14,
        fontWeight: '600',
    },
    instructions: {
        padding: 20,
        backgroundColor: theme.colors.surface,
        marginHorizontal: 20,
        borderRadius: theme.radius.md,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        ...theme.shadows.light,
    },
    instructionText: {
        ...theme.typography.caption,
        marginVertical: 4,
    },
    errorContainer: {
        margin: 20,
        padding: 15,
        backgroundColor: theme.colors.dangerSoft,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.danger,
    },
    errorText: {
        color: theme.colors.danger,
        textAlign: 'center',
        fontWeight: '500',
    },
    buttonContainer: {
        padding: 20,
    },
    button: {
        backgroundColor: theme.colors.primary,
        paddingVertical: 16,
        borderRadius: theme.radius.md,
        alignItems: 'center',
        ...theme.shadows.light,
    },
    buttonDisabled: {
        backgroundColor: theme.colors.borderDark,
        shadowOpacity: 0,
    },
    cancelButton: {
        backgroundColor: theme.colors.surface,
        borderWidth: 1,
        borderColor: theme.colors.borderDark,
        elevation: 0,
        shadowOpacity: 0,
    },
    buttonText: {
        color: '#FFFFFF',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 0.5,
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
        color: theme.colors.textSoft,
        fontSize: 12,
    },
});

export default ScanScreen;
