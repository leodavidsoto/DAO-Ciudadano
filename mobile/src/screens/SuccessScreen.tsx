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
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ChileanIDData } from '../services/nfcService';

interface SuccessScreenProps {
    navigation: any;
    route: {
        params: {
            idData: ChileanIDData;
            serialNumber: string;
        };
    };
}

const SuccessScreen: React.FC<SuccessScreenProps> = ({ navigation, route }) => {
    const { idData, serialNumber } = route.params;

    const handleContinue = () => {
        navigation.navigate('Wallet', { idData, serialNumber });
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.content}>
                {/* Success Icon */}
                <View style={styles.successIcon}>
                    <Text style={styles.checkmark}>✓</Text>
                </View>

                <Text style={styles.title}>CHIP VERIFICADO</Text>
                <Text style={styles.subtitle}>
                    La identificación ha sido leída exitosamente
                </Text>

                {/* Data Card */}
                <View style={styles.dataCard}>
                    <Text style={styles.cardTitle}>DATOS DEL CHIP</Text>

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
                        <Text style={styles.hashLabel}>Hash de Verificación:</Text>
                        <Text style={styles.hashValue}>
                            {serialNumber.substring(0, 8)}...{serialNumber.substring(serialNumber.length - 4)}
                        </Text>
                    </View>
                </View>

                {/* Security Badge */}
                <View style={styles.securityBadge}>
                    <Text style={styles.securityIcon}>🔒</Text>
                    <Text style={styles.securityText}>
                        Verificación criptográfica completada
                    </Text>
                </View>
            </ScrollView>

            {/* Continue Button */}
            <View style={styles.buttonContainer}>
                <TouchableOpacity style={styles.button} onPress={handleContinue}>
                    <Text style={styles.buttonText}>CONECTAR WALLET</Text>
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
