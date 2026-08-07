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
import nfcService, {
    describeReadFailure,
    isValidCAN,
    isVerifiedNFCReadResult,
    normalizeCAN,
    NFCFailureGuidance,
    PACE_CAN_LENGTH,
} from '../services/nfcService';
import { theme } from '../styles/theme';

interface ScanScreenProps {
    navigation: any;
}

const ScanScreen: React.FC<ScanScreenProps> = ({ navigation }) => {
    const [isScanning, setIsScanning] = useState(false);
    const [nfcEnabled, setNfcEnabled] = useState(false);
    const [failure, setFailure] = useState<NFCFailureGuidance | null>(null);
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
        const normalizedCan = normalizeCAN(can);
        if (!isValidCAN(normalizedCan)) {
            setFailure({
                title: 'Falta el CAN completo',
                detail: `Escribe los ${PACE_CAN_LENGTH} dígitos del Card Access Number impresos en tu cédula. No es el RUT ni el número de documento.`,
                action: 'fix_can',
            });
            return;
        }

        if (!nfcEnabled) {
            Alert.alert('NFC Deshabilitado', 'Por favor habilita NFC primero');
            return;
        }

        setIsScanning(true);
        setFailure(null);
        const attempt = ++scanAttempt.current;
        try {
            const result = await nfcService.readChileanIDPACE(normalizedCan);
            if (attempt !== scanAttempt.current) return;

            if (isVerifiedNFCReadResult(result)) {
                navigation.navigate('Success', { result });
            } else {
                setFailure(describeReadFailure(result));
            }
        } catch (err: any) {
            // A throw here is a bug in the bridge, not a chip response: the
            // service is supposed to resolve every failure as a typed result.
            if (attempt === scanAttempt.current) {
                setFailure({
                    title: 'Error inesperado durante la lectura',
                    detail: 'Vuelve a intentarlo. Si persiste, repórtalo al equipo.',
                    action: 'app_defect',
                    technicalDetail: typeof err?.message === 'string' ? err.message : undefined,
                });
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

    const handleCanChange = (value: string) => {
        setCan(normalizeCAN(value));
        // Stale guidance about a wrong CAN must not survive the correction.
        if (failure?.action === 'fix_can') setFailure(null);
    };

    const canIsComplete = isValidCAN(can);
    const canNeedsCorrection = failure?.action === 'fix_can' || (can.length > 0 && !canIsComplete);

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
                        <Text style={styles.inputLabel}>Card Access Number (CAN)</Text>
                        <TextInput
                            style={[
                                styles.input,
                                canNeedsCorrection && styles.inputInvalid,
                            ]}
                            placeholder="000000"
                            placeholderTextColor={theme.colors.textSoft}
                            value={can}
                            onChangeText={handleCanChange}
                            keyboardType="number-pad"
                            maxLength={PACE_CAN_LENGTH}
                            editable={!isScanning}
                            accessibilityLabel="Card Access Number de la cédula"
                        />
                        <Text style={styles.inputHint}>
                            Son los {PACE_CAN_LENGTH} dígitos del CAN impresos en tu cédula.
                            No es el RUT ni el número de documento.
                        </Text>
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

            {/* Failure guidance */}
            {failure && (
                <View
                    style={[
                        styles.errorContainer,
                        failure.action === 'app_defect' && styles.warningContainer,
                    ]}
                >
                    <Text
                        style={[
                            styles.errorTitle,
                            failure.action === 'app_defect' && styles.warningText,
                        ]}
                    >
                        ⚠️ {failure.title}
                    </Text>
                    <Text style={styles.errorDetail}>{failure.detail}</Text>
                    {failure.technicalDetail && (
                        <Text style={styles.errorTechnical}>{failure.technicalDetail}</Text>
                    )}
                    {failure.action === 'enable_nfc' && (
                        <TouchableOpacity
                            style={styles.inlineAction}
                            onPress={() => nfcService.requestEnable()}
                        >
                            <Text style={styles.inlineActionText}>Abrir ajustes de NFC</Text>
                        </TouchableOpacity>
                    )}
                </View>
            )}

            {/* Action Buttons */}
            <View style={styles.buttonContainer}>
                {!isScanning ? (
                    <TouchableOpacity
                        style={[
                            styles.button,
                            (!nfcEnabled || !canIsComplete) && styles.buttonDisabled,
                        ]}
                        onPress={handleStartScan}
                        disabled={!nfcEnabled || !canIsComplete}
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
    inputInvalid: {
        borderColor: theme.colors.danger,
        backgroundColor: theme.colors.dangerSoft,
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
    warningContainer: {
        backgroundColor: theme.colors.warningSoft,
        borderColor: theme.colors.warning,
    },
    errorTitle: {
        color: theme.colors.danger,
        fontSize: 15,
        fontWeight: '700',
        marginBottom: 6,
    },
    warningText: {
        color: theme.colors.warning,
    },
    errorDetail: {
        ...theme.typography.caption,
        color: theme.colors.text,
    },
    errorTechnical: {
        ...theme.typography.caption,
        color: theme.colors.textSoft,
        fontSize: 12,
        marginTop: 8,
    },
    inlineAction: {
        marginTop: 12,
        alignSelf: 'flex-start',
    },
    inlineActionText: {
        color: theme.colors.primary,
        fontWeight: '700',
        textDecorationLine: 'underline',
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
