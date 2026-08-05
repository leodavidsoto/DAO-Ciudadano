/** Display only identity data that crossed the verified NFC boundary. */

import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
    isVerifiedNFCReadResult,
    type VerifiedNFCReadResult,
} from '../services/nfcService';
import { theme } from '../styles/theme';

interface SuccessScreenProps {
    navigation: any;
    route?: {
        params?: {
            result?: VerifiedNFCReadResult;
        };
    };
}

const SuccessScreen: React.FC<SuccessScreenProps> = ({ navigation, route }) => {
    // Navigation is another runtime boundary. Do not trust a route boolean or
    // display identity fields unless the full evidence object still validates.
    const candidate = route?.params?.result;
    const identityVerified = isVerifiedNFCReadResult(candidate);
    const idData = identityVerified ? candidate.data : null;
    const verification = identityVerified ? candidate.verification : null;

    const handleContinue = () => {
        if (!identityVerified) {
            navigation.navigate('Scan');
            return;
        }
        navigation.navigate('Wallet');
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.content}>
                <View style={identityVerified ? styles.successIcon : styles.warningIcon}>
                    <Text style={identityVerified ? styles.checkmark : styles.warningMark}>
                        {identityVerified ? '✓' : '!'}
                    </Text>
                </View>

                <Text style={identityVerified ? styles.title : styles.titleWarning}>
                    {identityVerified ? 'DOCUMENTO VERIFICADO' : 'LECTURA NO VERIFICADA'}
                </Text>
                <Text style={styles.subtitle}>
                    {identityVerified
                        ? 'La app comprobó localmente los datos firmados de la cédula y su cadena CSCA chilena instalada.'
                        : 'La evidencia de autenticación pasiva está ausente o incompleta. No se mostrarán datos del documento.'}
                </Text>

                {idData && verification && (
                    <View style={styles.dataCard}>
                        <Text style={styles.cardTitle}>DATOS AUTENTICADOS (DG1)</Text>

                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Documento:</Text>
                            <Text style={styles.dataValue}>{idData.documentNumber}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nombre:</Text>
                            <Text style={styles.dataValue}>
                                {idData.firstName} {idData.lastName}
                            </Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Emisor:</Text>
                            <Text style={styles.dataValue}>{idData.issuingState}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nacionalidad:</Text>
                            <Text style={styles.dataValue}>{idData.nationality}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nacimiento:</Text>
                            <Text style={styles.dataValue}>{idData.dateOfBirth}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Vencimiento:</Text>
                            <Text style={styles.dataValue}>{idData.dateOfExpiry}</Text>
                        </View>

                        <View style={styles.evidenceContainer}>
                            <Text style={styles.evidenceTitle}>EVIDENCIA VERIFICADA</Text>
                            <Text style={styles.evidenceText}>✓ Canal PACE-CAN establecido</Text>
                            <Text style={styles.evidenceText}>✓ DG1, DG2 y EF.SOD presentes</Text>
                            <Text style={styles.evidenceText}>✓ Hashes de data groups</Text>
                            <Text style={styles.evidenceText}>✓ Firma EF.SOD</Text>
                            <Text style={styles.evidenceText}>✓ Perfil de cédula chilena</Text>
                            <Text style={styles.evidenceText}>✓ Documento dentro de vigencia</Text>
                            <Text style={styles.evidenceText}>✓ Ancla CSCA chilena del Registro Civil</Text>
                            <Text style={styles.evidenceText}>
                                ✓ Cadena CSCA ({verification.trustAnchorsInstalled} anclas instaladas)
                            </Text>
                        </View>
                    </View>
                )}

                {identityVerified ? (
                    <View style={styles.securityBadge}>
                        <Text style={styles.securityIcon}>🔒</Text>
                        <Text style={styles.securityText}>
                            Autenticación pasiva local completada. No comprueba revocación ni descarta por sí sola un chip clonado; la emisión sigue bloqueada hasta contar con atestación autorizada.
                        </Text>
                    </View>
                ) : (
                    <View style={styles.pendingBadge}>
                        <Text style={styles.securityIcon}>⚠️</Text>
                        <Text style={styles.pendingText}>
                            Flujo detenido: vuelve a escanear. Una lectura no verificada no puede continuar a membresía.
                        </Text>
                    </View>
                )}
            </ScrollView>

            <View style={styles.buttonContainer}>
                <TouchableOpacity style={styles.button} onPress={handleContinue}>
                    <Text style={styles.buttonText}>
                        {identityVerified ? 'CONTINUAR A MEMBRESÍA' : 'VOLVER A ESCANEAR'}
                    </Text>
                </TouchableOpacity>
            </View>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: theme.colors.background,
    },
    content: {
        padding: 20,
        alignItems: 'center',
    },
    successIcon: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: theme.colors.successSoft,
        borderWidth: 2,
        borderColor: theme.colors.success,
        justifyContent: 'center',
        alignItems: 'center',
        marginVertical: 30,
        ...theme.shadows.light,
    },
    checkmark: {
        fontSize: 48,
        color: theme.colors.success,
    },
    title: {
        ...theme.typography.title,
        color: theme.colors.success,
        textAlign: 'center',
    },
    titleWarning: {
        ...theme.typography.title,
        color: theme.colors.warning,
        textAlign: 'center',
    },
    warningIcon: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: theme.colors.warningSoft,
        borderWidth: 2,
        borderColor: theme.colors.warning,
        justifyContent: 'center',
        alignItems: 'center',
        marginVertical: 30,
        ...theme.shadows.light,
    },
    warningMark: {
        fontSize: 48,
        color: theme.colors.warning,
        fontWeight: 'bold',
    },
    pendingBadge: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        marginTop: 20,
        padding: 12,
        backgroundColor: theme.colors.warningSoft,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.warning,
    },
    pendingText: {
        ...theme.typography.caption,
        color: theme.colors.warning,
        flex: 1,
    },
    subtitle: {
        ...theme.typography.caption,
        marginTop: 8,
        marginBottom: 30,
        textAlign: 'center',
    },
    dataCard: {
        width: '100%',
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        padding: 20,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        ...theme.shadows.light,
    },
    cardTitle: {
        ...theme.typography.caption,
        color: theme.colors.primary,
        fontWeight: 'bold',
        marginBottom: 16,
        textAlign: 'center',
    },
    dataRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 10,
        borderBottomWidth: 1,
        borderBottomColor: theme.colors.borderLight,
    },
    dataLabel: {
        ...theme.typography.body,
        color: theme.colors.textSoft,
    },
    dataValue: {
        ...theme.typography.body,
        fontWeight: '600',
        flex: 1,
        textAlign: 'right',
        marginLeft: 10,
    },
    evidenceContainer: {
        marginTop: 16,
        padding: 12,
        backgroundColor: theme.colors.primarySoft,
        borderRadius: theme.radius.sm,
    },
    evidenceTitle: {
        ...theme.typography.caption,
        color: theme.colors.primary,
        fontWeight: 'bold',
        marginBottom: 8,
    },
    evidenceText: {
        ...theme.typography.caption,
        color: theme.colors.primaryHover,
        marginVertical: 2,
    },
    securityBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 20,
        padding: 12,
        backgroundColor: theme.colors.successSoft,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.success,
    },
    securityIcon: {
        fontSize: 20,
        marginRight: 10,
    },
    securityText: {
        ...theme.typography.caption,
        color: theme.colors.success,
        flex: 1,
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
    buttonText: {
        color: '#FFFFFF',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 0.5,
    },
});

export default SuccessScreen;
