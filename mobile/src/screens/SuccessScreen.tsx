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
        backgroundColor: '#0a0a1a',
    },
    content: {
        padding: 20,
        alignItems: 'center',
    },
    successIcon: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: '#00FF0020',
        borderWidth: 3,
        borderColor: '#00FF00',
        justifyContent: 'center',
        alignItems: 'center',
        marginVertical: 30,
    },
    checkmark: {
        fontSize: 48,
        color: '#00FF00',
    },
    title: {
        fontSize: 24,
        fontWeight: 'bold',
        color: '#00FF00',
        letterSpacing: 2,
    },
    titleWarning: {
        fontSize: 24,
        fontWeight: 'bold',
        color: '#FFA500',
        letterSpacing: 2,
        textAlign: 'center',
    },
    warningIcon: {
        width: 100,
        height: 100,
        borderRadius: 50,
        backgroundColor: '#FFA50020',
        borderWidth: 3,
        borderColor: '#FFA500',
        justifyContent: 'center',
        alignItems: 'center',
        marginVertical: 30,
    },
    warningMark: {
        fontSize: 48,
        color: '#FFA500',
        fontWeight: 'bold',
    },
    pendingBadge: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        marginTop: 20,
        padding: 12,
        backgroundColor: '#FFA50010',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#FFA50040',
    },
    pendingText: {
        color: '#FFCC80',
        fontSize: 12,
        flex: 1,
        lineHeight: 17,
    },
    subtitle: {
        fontSize: 14,
        color: '#888',
        marginTop: 8,
        marginBottom: 30,
        textAlign: 'center',
    },
    dataCard: {
        width: '100%',
        backgroundColor: '#0a0a2a',
        borderRadius: 16,
        padding: 20,
        borderWidth: 1,
        borderColor: '#00FFFF30',
    },
    cardTitle: {
        fontSize: 12,
        color: '#00FFFF',
        letterSpacing: 1,
        marginBottom: 16,
        textAlign: 'center',
    },
    dataRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 10,
        borderBottomWidth: 1,
        borderBottomColor: '#ffffff10',
    },
    dataLabel: {
        color: '#666',
        fontSize: 14,
    },
    dataValue: {
        color: '#fff',
        fontSize: 14,
        fontWeight: '600',
    },
    evidenceContainer: {
        marginTop: 16,
        padding: 12,
        backgroundColor: '#00FFFF10',
        borderRadius: 8,
    },
    evidenceTitle: {
        color: '#00FFFF',
        fontSize: 11,
        marginBottom: 8,
        letterSpacing: 1,
    },
    evidenceText: {
        color: '#B8FFFF',
        fontSize: 12,
        marginVertical: 2,
    },
    securityBadge: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 20,
        padding: 12,
        backgroundColor: '#00FF0010',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#00FF0030',
    },
    securityIcon: {
        fontSize: 20,
        marginRight: 10,
    },
    securityText: {
        color: '#00FF00',
        fontSize: 12,
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
    buttonText: {
        color: '#000',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
});

export default SuccessScreen;
