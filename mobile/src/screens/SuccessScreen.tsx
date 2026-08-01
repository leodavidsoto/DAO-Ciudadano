/**
 * Success Screen - Display scan results and proceed to wallet connection
 */

import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    ScrollView,
    Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChileanIDData } from '../services/nfcService';

interface SuccessScreenProps {
    navigation: any;
    route: {
        params: {
            idData: ChileanIDData;
            serialNumber: string;
            identityVerified?: boolean;
        };
    };
}

const SuccessScreen: React.FC<SuccessScreenProps> = ({ navigation, route }) => {
    const { idData, serialNumber, identityVerified = false } = route.params;

    const handleContinue = () => {
        navigation.navigate('Wallet', { idData, serialNumber, identityVerified });
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.content}>
                {/* Estado de lectura. El ícono y el texto reflejan si la
                    identidad fue verificada criptográficamente o si solo se
                    detectó un tag NFC: decir "verificado" sin serlo es
                    justamente lo que permitía registrarse con cualquier
                    tarjeta. */}
                <View style={identityVerified ? styles.successIcon : styles.warningIcon}>
                    <Text style={identityVerified ? styles.checkmark : styles.warningMark}>
                        {identityVerified ? '✓' : '!'}
                    </Text>
                </View>

                <Text style={identityVerified ? styles.title : styles.titleWarning}>
                    {identityVerified ? 'IDENTIDAD VERIFICADA' : 'LECTURA NO VERIFICADA'}
                </Text>
                <Text style={styles.subtitle}>
                    {identityVerified
                        ? 'La identificación fue autenticada criptográficamente'
                        : 'Se detectó un tag NFC, pero esto no acredita identidad ni autenticidad'}
                </Text>

                {/* Data Card */}
                <View style={styles.dataCard}>
                    <Text style={styles.cardTitle}>
                        {identityVerified ? 'DATOS AUTENTICADOS' : 'DATOS DE LA LECTURA PILOTO'}
                    </Text>

                    <View style={styles.dataRow}>
                        <Text style={styles.dataLabel}>Serial NFC:</Text>
                        <Text style={styles.dataValue}>{serialNumber}</Text>
                    </View>

                    {idData.documentNumber && (
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Documento:</Text>
                            <Text style={styles.dataValue}>{idData.documentNumber}</Text>
                        </View>
                    )}

                    {idData.rut && (
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>RUT:</Text>
                            <Text style={styles.dataValue}>{idData.rut}</Text>
                        </View>
                    )}

                    {idData.firstName && (
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nombre:</Text>
                            <Text style={styles.dataValue}>
                                {idData.firstName} {idData.lastName}
                            </Text>
                        </View>
                    )}

                    <View style={styles.hashContainer}>
                        {/* Antes decía "Hash de Verificación", pero es el serial
                            del tag recortado -- ni es un hash ni verifica nada. */}
                        <Text style={styles.hashLabel}>Identificador técnico del tag:</Text>
                        <Text style={styles.hashValue}>
                            {serialNumber.substring(0, 8)}...{serialNumber.substring(serialNumber.length - 4)}
                        </Text>
                    </View>
                </View>

                {/* Estado real de la verificación criptográfica */}
                {identityVerified ? (
                    <View style={styles.securityBadge}>
                        <Text style={styles.securityIcon}>🔒</Text>
                        <Text style={styles.securityText}>
                            Verificación criptográfica completada
                        </Text>
                    </View>
                ) : (
                    <View style={styles.pendingBadge}>
                        <Text style={styles.securityIcon}>⚠️</Text>
                        <Text style={styles.pendingText}>
                            Lectura sin verificar: el número de serie de un chip no prueba
                            identidad. La lectura autenticada de la cédula está en desarrollo.
                        </Text>
                    </View>
                )}
            </ScrollView>

            {/* Continue Button */}
            <View style={styles.buttonContainer}>
                <TouchableOpacity style={styles.button} onPress={handleContinue}>
                    <Text style={styles.buttonText}>
                        {identityVerified ? 'CONTINUAR A MI BILLETERA' : 'CONTINUAR SIN REGISTRO'}
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
    hashContainer: {
        marginTop: 16,
        padding: 12,
        backgroundColor: '#00FFFF10',
        borderRadius: 8,
    },
    hashLabel: {
        color: '#00FFFF',
        fontSize: 11,
        marginBottom: 4,
    },
    hashValue: {
        color: '#00FFFF',
        fontSize: 14,
        fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
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
