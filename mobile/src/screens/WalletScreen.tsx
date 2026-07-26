/**
 * Wallet Screen - Look up DAO membership by wallet address
 *
 * Queries the backend for an existing membership record. Shows an honest
 * empty state when there is none — no fabricated data.
 */

import React, { useState } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    TextInput,
    ActivityIndicator,
    ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiService from '../services/apiService';

interface WalletScreenProps {
    navigation: any;
}

interface MemberInfo {
    token_id: number;
    wallet_address: string;
    assurance_level: string;
    status: string;
}

const ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;

const WalletScreen: React.FC<WalletScreenProps> = ({ navigation }) => {
    const [address, setAddress] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [searched, setSearched] = useState(false);
    const [member, setMember] = useState<MemberInfo | null>(null);

    const handleLookup = async () => {
        const trimmed = address.trim();
        if (!ADDRESS_REGEX.test(trimmed)) {
            setError('Dirección inválida. Debe ser una dirección Ethereum (0x + 40 caracteres hex).');
            return;
        }

        setLoading(true);
        setError('');
        setMember(null);
        setSearched(false);

        try {
            const result = await apiService.getMembershipStatus(trimmed.toLowerCase());
            setSearched(true);
            if (result.found) {
                setMember(result.member);
            }
        } catch (e) {
            setError('No se pudo consultar el servidor. Verifica tu conexión.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.content}>
                <Text style={styles.title}>CONSULTA DE MEMBRESÍA</Text>
                <Text style={styles.subtitle}>
                    Ingresa tu dirección de wallet para verificar si tienes una membresía registrada
                </Text>

                <TextInput
                    style={styles.input}
                    placeholder="0x..."
                    placeholderTextColor="#444"
                    value={address}
                    onChangeText={setAddress}
                    autoCapitalize="none"
                    autoCorrect={false}
                />

                <TouchableOpacity
                    style={[styles.button, loading && styles.buttonDisabled]}
                    onPress={handleLookup}
                    disabled={loading}
                >
                    {loading ? (
                        <ActivityIndicator color="#000" />
                    ) : (
                        <Text style={styles.buttonText}>CONSULTAR</Text>
                    )}
                </TouchableOpacity>

                {error !== '' && (
                    <View style={styles.errorBox}>
                        <Text style={styles.errorText}>{error}</Text>
                    </View>
                )}

                {searched && member && (
                    <View style={styles.resultCard}>
                        <Text style={styles.resultTitle}>MEMBRESÍA ENCONTRADA</Text>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Token ID:</Text>
                            <Text style={styles.dataValue}>#{member.token_id}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nivel:</Text>
                            <Text style={styles.dataValue}>{member.assurance_level}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Estado:</Text>
                            <Text style={styles.dataValue}>{member.status}</Text>
                        </View>
                    </View>
                )}

                {searched && !member && (
                    <View style={styles.emptyCard}>
                        <Text style={styles.emptyTitle}>SIN MEMBRESÍA</Text>
                        <Text style={styles.emptyText}>
                            Esta dirección no tiene una membresía registrada. Completa la
                            verificación de identidad para obtener una.
                        </Text>
                        <TouchableOpacity
                            style={styles.secondaryButton}
                            onPress={() => navigation.navigate('Scan')}
                        >
                            <Text style={styles.secondaryButtonText}>ESCANEAR CÉDULA</Text>
                        </TouchableOpacity>
                    </View>
                )}
            </ScrollView>
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
    },
    title: {
        fontSize: 20,
        fontWeight: 'bold',
        color: '#00FFFF',
        letterSpacing: 2,
        textAlign: 'center',
        marginTop: 20,
    },
    subtitle: {
        fontSize: 13,
        color: '#888',
        textAlign: 'center',
        marginTop: 8,
        marginBottom: 24,
    },
    input: {
        backgroundColor: '#0a0a2a',
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#00FFFF30',
        color: '#fff',
        paddingHorizontal: 16,
        paddingVertical: 14,
        fontSize: 14,
        marginBottom: 16,
    },
    button: {
        backgroundColor: '#00FFFF',
        paddingVertical: 16,
        borderRadius: 12,
        alignItems: 'center',
    },
    buttonDisabled: {
        opacity: 0.6,
    },
    buttonText: {
        color: '#000',
        fontSize: 15,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    errorBox: {
        marginTop: 16,
        padding: 12,
        backgroundColor: '#FF073A15',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#FF073A50',
    },
    errorText: {
        color: '#FF6B81',
        fontSize: 13,
    },
    resultCard: {
        marginTop: 24,
        backgroundColor: '#0a0a2a',
        borderRadius: 16,
        padding: 20,
        borderWidth: 1,
        borderColor: '#00FF0030',
    },
    resultTitle: {
        fontSize: 13,
        color: '#00FF00',
        letterSpacing: 1,
        marginBottom: 12,
        textAlign: 'center',
    },
    dataRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 8,
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
    emptyCard: {
        marginTop: 24,
        backgroundColor: '#0a0a2a',
        borderRadius: 16,
        padding: 20,
        borderWidth: 1,
        borderColor: '#ffffff15',
        alignItems: 'center',
    },
    emptyTitle: {
        fontSize: 13,
        color: '#888',
        letterSpacing: 1,
        marginBottom: 8,
    },
    emptyText: {
        fontSize: 13,
        color: '#666',
        textAlign: 'center',
        marginBottom: 16,
    },
    secondaryButton: {
        borderWidth: 1,
        borderColor: '#00FFFF50',
        borderRadius: 12,
        paddingVertical: 12,
        paddingHorizontal: 24,
    },
    secondaryButtonText: {
        color: '#00FFFF',
        fontSize: 13,
        fontWeight: '600',
        letterSpacing: 1,
    },
});

export default WalletScreen;
