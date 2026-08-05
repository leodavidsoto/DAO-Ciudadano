/**
 * Wallet Screen
 *
 * Dos caminos:
 * 1. Crear billetera nueva en el dispositivo (implementado acá): genera un
 *    par de llaves real, muestra la frase semilla UNA vez, la guarda cifrada
 *    en el almacén seguro del sistema (Keychain/Keystore vía
 *    react-native-keychain) y firma una sesión SIWE real contra el backend.
 * 2. Conectar billetera externa (MetaMask, WalletConnect) — próximamente,
 *    botón visible pero deshabilitado para no prometer algo que no existe.
 *
 * A local NFC verification is never an issuance grant. This screen only
 * creates/loads the wallet, establishes SIWE, and displays membership state.
 * Issuance remains blocked until the backend defines and verifies a scoped,
 * single-use grant or attestation.
 */

import React, { useEffect, useState, useCallback } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    TextInput,
    ActivityIndicator,
    ScrollView,
    Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Wallet as EthersWallet } from 'ethers';
import apiService from '../services/apiService';
import walletService, { GeneratedWallet } from '../services/walletService';
import { theme } from '../styles/theme';

interface MemberInfo {
    token_id: number;
    wallet_address: string;
    assurance_level: string;
    status: string;
    tx_hash?: string | null;
}

interface WalletScreenProps {
    navigation: any;
}

type ScreenState =
    | 'checking'
    | 'choose'
    | 'backup'
    | 'signing-in'
    | 'ready'
    | 'lookup';

const ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;

const WalletScreen: React.FC<WalletScreenProps> = ({ navigation }) => {
    const [state, setState] = useState<ScreenState>('checking');
    const [pendingWallet, setPendingWallet] = useState<GeneratedWallet | null>(null);
    const [backupConfirmed, setBackupConfirmed] = useState(false);
    const [address, setAddress] = useState<string | null>(null);
    const [member, setMember] = useState<MemberInfo | null>(null);
    const [error, setError] = useState('');

    // Manual lookup (fallback, sin billetera en este dispositivo)
    const [lookupAddress, setLookupAddress] = useState('');
    const [lookupLoading, setLookupLoading] = useState(false);
    const [lookupSearched, setLookupSearched] = useState(false);
    const [lookupMember, setLookupMember] = useState<MemberInfo | null>(null);

    const signInAndProceed = useCallback(async (wallet: EthersWallet) => {
        setState('signing-in');
        setError('');
        try {
            const challenge = await apiService.walletChallenge(wallet.address);
            const signature = await walletService.signMessage(wallet, challenge.message);
            const session = await apiService.walletVerify(wallet.address, challenge.nonce, signature);
            apiService.setToken(session.token);
            setAddress(wallet.address);

            const status = await apiService.getMembershipStatus(wallet.address.toLowerCase());
            if (status.found) {
                setMember(status.member);
                setState('ready');
                return;
            }

            setError(
                'Emisión bloqueada: una verificación NFC local no autoriza un alta. ' +
                'El backend aún no entrega ni verifica una atestación de identidad de un solo uso. ' +
                'No se solicitó una credencial ni un nivel de assurance.',
            );
            setState('ready');
        } catch (e: any) {
            setError(
                e?.response?.data?.detail || e?.message || 'Error estableciendo la sesión de wallet',
            );
            setState('ready');
        }
    }, []);

    // Al entrar, revisa si ya hay una billetera guardada en el dispositivo.
    useEffect(() => {
        let alive = true;
        (async () => {
            try {
                const hasWallet = await walletService.hasWallet();
                if (!alive) return;
                if (hasWallet) {
                    const wallet = await walletService.loadWallet();
                    if (wallet) {
                        await signInAndProceed(wallet);
                        return;
                    }
                }
                setState('choose');
            } catch {
                if (alive) setState('choose');
            }
        })();
        return () => { alive = false; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const handleCreateWallet = () => {
        try {
            const generated = walletService.generate();
            setPendingWallet(generated);
            setBackupConfirmed(false);
            setState('backup');
        } catch (e: any) {
            setError(e?.message || 'No se pudo generar la billetera');
        }
    };

    const handleConfirmBackup = async () => {
        if (!pendingWallet) return;
        try {
            await walletService.saveWallet(pendingWallet.privateKey, pendingWallet.address);
            const wallet = new EthersWallet(pendingWallet.privateKey);
            setPendingWallet(null);
            await signInAndProceed(wallet);
        } catch (e: any) {
            setError(e?.message || 'No se pudo guardar la billetera de forma segura');
        }
    };

    const handleLookup = async () => {
        const trimmed = lookupAddress.trim();
        if (!ADDRESS_REGEX.test(trimmed)) {
            setError('Dirección inválida. Debe ser una dirección Ethereum (0x + 40 caracteres hex).');
            return;
        }
        setLookupLoading(true);
        setError('');
        setLookupMember(null);
        setLookupSearched(false);
        try {
            const result = await apiService.getMembershipStatus(trimmed.toLowerCase());
            setLookupSearched(true);
            if (result.found) setLookupMember(result.member);
        } catch {
            setError('No se pudo consultar el servidor. Verifica tu conexión.');
        } finally {
            setLookupLoading(false);
        }
    };

    // === Render: comprobando billetera existente ===
    if (state === 'checking' || state === 'signing-in') {
        const label = state === 'checking'
            ? 'SINCRONIZANDO MEMBRESÍA...'
            : 'ESTABLECIENDO CONEXIÓN SEGURA SIWE...';
        return (
            <SafeAreaView style={styles.container}>
                <View style={styles.centered}>
                    <ActivityIndicator size="large" color={theme.colors.primary} />
                    <Text style={styles.loadingText}>{label}</Text>
                </View>
            </SafeAreaView>
        );
    }

    // === Render: elegir cómo obtener wallet ===
    if (state === 'choose') {
        return (
            <SafeAreaView style={styles.container}>
                <ScrollView contentContainerStyle={styles.content}>
                    <Text style={styles.title}>BÓVEDA CRIPTOGRÁFICA</Text>
                    <Text style={styles.subtitle}>
                        Genera un enclave local seguro en tu dispositivo. Tu identidad real nunca abandona el teléfono.
                    </Text>

                    <TouchableOpacity style={styles.button} onPress={handleCreateWallet}>
                        <Text style={styles.buttonText}>GENERAR LLAVES LOCALES</Text>
                    </TouchableOpacity>
                    <Text style={styles.hint}>
                        Esta billetera firma la sesión SIWE. No contiene ni sustituye una atestación de identidad.
                    </Text>

                    <TouchableOpacity style={styles.buttonDisabledOutline} disabled>
                        <Text style={styles.buttonDisabledText}>CONECTAR BILLETERA EXTERNA</Text>
                    </TouchableOpacity>
                    <Text style={styles.hint}>
                        Próximamente: conectar MetaMask u otra wallet ya existente.
                    </Text>

                    {error !== '' && (
                        <View style={styles.errorBox}>
                            <Text style={styles.errorText}>{error}</Text>
                        </View>
                    )}

                    <TouchableOpacity
                        style={styles.linkButton}
                        onPress={() => setState('lookup')}
                    >
                        <Text style={styles.linkButtonText}>
                            Ya tengo una dirección, solo quiero consultarla
                        </Text>
                    </TouchableOpacity>
                </ScrollView>
            </SafeAreaView>
        );
    }

    // === Render: mostrar frase semilla y confirmar respaldo ===
    if (state === 'backup' && pendingWallet) {
        return (
            <SafeAreaView style={styles.container}>
                <ScrollView contentContainerStyle={styles.content}>
                    <Text style={styles.title}>CLAVE DE RECUPERACIÓN</Text>
                    <View style={styles.warningBox}>
                        <Text style={styles.warningText}>
                            Transcribe estos 12 mnemónicos a un soporte físico seguro.
                            Esta frase controla la billetera local. El Estado no posee copia de esta llave.
                        </Text>
                    </View>

                    <View style={styles.mnemonicBox}>
                        <Text style={styles.mnemonicText}>{pendingWallet.mnemonic}</Text>
                    </View>

                    <View style={styles.dataRow}>
                        <Text style={styles.dataLabel}>Dirección:</Text>
                        <Text style={styles.dataValueSmall}>{pendingWallet.address}</Text>
                    </View>

                    <TouchableOpacity
                        style={styles.checkboxRow}
                        onPress={() => setBackupConfirmed(!backupConfirmed)}
                    >
                        <View style={[styles.checkbox, backupConfirmed && styles.checkboxChecked]}>
                            {backupConfirmed && <Text style={styles.checkboxMark}>✓</Text>}
                        </View>
                        <Text style={styles.checkboxLabel}>Ya guardé mi frase de respaldo</Text>
                    </TouchableOpacity>

                    <TouchableOpacity
                        style={[styles.button, !backupConfirmed && styles.buttonDisabled]}
                        disabled={!backupConfirmed}
                        onPress={() => {
                            Alert.alert(
                                'Confirmar',
                                '¿Ya guardaste tu frase de respaldo en un lugar seguro? No se volverá a mostrar.',
                                [
                                    { text: 'Volver', style: 'cancel' },
                                    { text: 'Sí, continuar', onPress: handleConfirmBackup },
                                ],
                            );
                        }}
                    >
                        <Text style={styles.buttonText}>CONTINUAR</Text>
                    </TouchableOpacity>

                    {error !== '' && (
                        <View style={styles.errorBox}>
                            <Text style={styles.errorText}>{error}</Text>
                        </View>
                    )}
                </ScrollView>
            </SafeAreaView>
        );
    }

    // === Render: billetera lista (con o sin membresía) ===
    if (state === 'ready') {
        return (
            <SafeAreaView style={styles.container}>
                <ScrollView contentContainerStyle={styles.content}>
                    <Text style={styles.title}>ENCLAVE ASEGURADO</Text>
                    {address && (
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Dirección:</Text>
                            <Text style={styles.dataValueSmall}>{address}</Text>
                        </View>
                    )}

                    {error !== '' && (
                        <View style={styles.errorBox}>
                            <Text style={styles.errorText}>{error}</Text>
                        </View>
                    )}

                    {member ? (
                        <View style={styles.resultCard}>
                            <Text style={styles.resultTitle}>REGISTRO REPORTADO POR EL SERVIDOR</Text>
                            <View style={styles.dataRow}>
                                <Text style={styles.dataLabel}>Token ID:</Text>
                                <Text style={styles.dataValue}>#{member.token_id}</Text>
                            </View>
                            <View style={styles.dataRow}>
                                <Text style={styles.dataLabel}>Nivel informado:</Text>
                                <Text style={styles.dataValue}>{member.assurance_level}</Text>
                            </View>
                            <View style={styles.dataRow}>
                                <Text style={styles.dataLabel}>Estado:</Text>
                                <Text style={styles.dataValue}>{member.status}</Text>
                            </View>
                            {member.tx_hash && (
                                <View style={styles.dataRow}>
                                    <Text style={styles.dataLabel}>Tx:</Text>
                                    <Text style={styles.dataValueSmall}>{member.tx_hash}</Text>
                                </View>
                            )}
                        </View>
                    ) : (
                        <View style={styles.emptyCard}>
                            <Text style={styles.emptyTitle}>EMISIÓN BLOQUEADA</Text>
                            <Text style={styles.emptyText}>
                                La lectura NFC local no es un permiso de alta. Falta que el backend emita y verifique una atestación autorizada antes de solicitar cualquier credencial.
                            </Text>
                            <TouchableOpacity
                                style={styles.secondaryButton}
                                onPress={() => navigation.navigate('Scan')}
                            >
                                <Text style={styles.secondaryButtonText}>VERIFICAR CÉDULA LOCALMENTE</Text>
                            </TouchableOpacity>
                            <Text style={styles.blockedHint}>
                                La verificación local no crea una membresía.
                            </Text>
                        </View>
                    )}
                </ScrollView>
            </SafeAreaView>
        );
    }

    // === Render: consulta manual por dirección (sin wallet en este dispositivo) ===
    return (
        <SafeAreaView style={styles.container}>
            <ScrollView contentContainerStyle={styles.content}>
                <Text style={styles.title}>CONSULTA DE MEMBRESÍA</Text>
                <Text style={styles.subtitle}>
                    Ingresa una dirección de wallet para verificar si tiene una membresía registrada
                </Text>

                <TextInput
                    style={styles.input}
                    placeholder="0x..."
                    placeholderTextColor="#444"
                    value={lookupAddress}
                    onChangeText={setLookupAddress}
                    autoCapitalize="none"
                    autoCorrect={false}
                />

                <TouchableOpacity
                    style={[styles.button, lookupLoading && styles.buttonDisabled]}
                    onPress={handleLookup}
                    disabled={lookupLoading}
                >
                    {lookupLoading ? (
                        <ActivityIndicator color="#FFFFFF" />
                    ) : (
                        <Text style={styles.buttonText}>CONSULTAR</Text>
                    )}
                </TouchableOpacity>

                {error !== '' && (
                    <View style={styles.errorBox}>
                        <Text style={styles.errorText}>{error}</Text>
                    </View>
                )}

                {lookupSearched && lookupMember && (
                    <View style={styles.resultCard}>
                        <Text style={styles.resultTitle}>REGISTRO ENCONTRADO (PILOTO)</Text>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Token ID:</Text>
                            <Text style={styles.dataValue}>#{lookupMember.token_id}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nivel informado:</Text>
                            <Text style={styles.dataValue}>{lookupMember.assurance_level}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Estado:</Text>
                            <Text style={styles.dataValue}>{lookupMember.status}</Text>
                        </View>
                    </View>
                )}

                {lookupSearched && !lookupMember && (
                    <View style={styles.emptyCard}>
                        <Text style={styles.emptyTitle}>SIN MEMBRESÍA</Text>
                        <Text style={styles.emptyText}>
                            Esta dirección no tiene una membresía registrada.
                        </Text>
                    </View>
                )}

                <TouchableOpacity style={styles.linkButton} onPress={() => setState('choose')}>
                    <Text style={styles.linkButtonText}>Volver</Text>
                </TouchableOpacity>
            </ScrollView>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: { flex: 1, backgroundColor: theme.colors.background },
    content: { padding: 20 },
    centered: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    loadingText: { color: theme.colors.primary, marginTop: 16, fontSize: 13, letterSpacing: 1 },
    title: {
        ...theme.typography.title,
        textAlign: 'center',
        marginTop: 20,
    },
    subtitle: {
        ...theme.typography.caption,
        textAlign: 'center',
        marginTop: 8,
        marginBottom: 24,
    },
    input: {
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.borderDark,
        color: theme.colors.ink,
        paddingHorizontal: 16,
        paddingVertical: 14,
        fontSize: 14,
        marginBottom: 16,
    },
    button: {
        backgroundColor: theme.colors.primary,
        paddingVertical: 16,
        borderRadius: theme.radius.md,
        alignItems: 'center',
        marginTop: 12,
        ...theme.shadows.light,
    },
    buttonDisabled: { opacity: 0.4 },
    buttonDisabledOutline: {
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        backgroundColor: theme.colors.surface,
        paddingVertical: 16,
        borderRadius: theme.radius.md,
        alignItems: 'center',
        marginTop: 12,
    },
    buttonDisabledText: {
        color: theme.colors.textSoft,
        fontSize: 15,
        fontWeight: 'bold',
        letterSpacing: 0.5,
    },
    buttonText: {
        color: '#FFFFFF',
        fontSize: 15,
        fontWeight: 'bold',
        letterSpacing: 0.5,
    },
    hint: {
        ...theme.typography.caption,
        fontSize: 11,
        marginTop: 8,
        marginBottom: 8,
        textAlign: 'center',
    },
    linkButton: { marginTop: 24, alignItems: 'center' },
    linkButtonText: { color: theme.colors.primary, fontSize: 13, textDecorationLine: 'underline' },
    errorBox: {
        marginTop: 16,
        padding: 12,
        backgroundColor: theme.colors.dangerSoft,
        borderRadius: theme.radius.sm,
        borderWidth: 1,
        borderColor: theme.colors.danger,
    },
    errorText: { color: theme.colors.danger, fontSize: 13 },
    warningBox: {
        backgroundColor: theme.colors.warningSoft,
        borderWidth: 1,
        borderColor: theme.colors.warning,
        borderRadius: theme.radius.md,
        padding: 16,
        marginBottom: 16,
    },
    warningText: { color: theme.colors.warning, fontSize: 13, lineHeight: 19 },
    mnemonicBox: {
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        padding: 20,
        marginBottom: 16,
        ...theme.shadows.light,
    },
    mnemonicText: {
        color: theme.colors.ink,
        fontSize: 16,
        lineHeight: 26,
        fontWeight: '600',
        letterSpacing: 0.5,
    },
    checkboxRow: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 16,
        marginBottom: 8,
    },
    checkbox: {
        width: 22,
        height: 22,
        borderRadius: 6,
        borderWidth: 2,
        borderColor: theme.colors.borderDark,
        marginRight: 12,
        justifyContent: 'center',
        alignItems: 'center',
    },
    checkboxChecked: { backgroundColor: theme.colors.primary, borderColor: theme.colors.primary },
    checkboxMark: { color: '#FFFFFF', fontWeight: 'bold', fontSize: 14 },
    checkboxLabel: { ...theme.typography.body, fontSize: 13, flex: 1 },
    resultCard: {
        marginTop: 24,
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        padding: 20,
        borderWidth: 1,
        borderColor: theme.colors.success,
        ...theme.shadows.light,
    },
    resultTitle: {
        fontSize: 13,
        color: theme.colors.success,
        letterSpacing: 1,
        marginBottom: 12,
        textAlign: 'center',
        fontWeight: 'bold',
    },
    dataRow: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderBottomColor: theme.colors.borderLight,
    },
    dataLabel: { color: theme.colors.textSoft, fontSize: 14 },
    dataValue: { color: theme.colors.ink, fontSize: 14, fontWeight: '600' },
    dataValueSmall: {
        color: theme.colors.ink,
        fontSize: 11,
        fontWeight: '600',
        flexShrink: 1,
        textAlign: 'right',
    },
    emptyCard: {
        marginTop: 24,
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        padding: 20,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        alignItems: 'center',
        ...theme.shadows.light,
    },
    emptyTitle: { ...theme.typography.title, fontSize: 15, marginBottom: 8 },
    emptyText: { ...theme.typography.caption, textAlign: 'center', marginBottom: 16 },
    secondaryButton: {
        borderWidth: 1,
        borderColor: theme.colors.borderDark,
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        paddingVertical: 12,
        paddingHorizontal: 24,
    },
    secondaryButtonText: {
        color: theme.colors.primary,
        fontSize: 13,
        fontWeight: '600',
        letterSpacing: 0.5,
    },
    blockedHint: {
        color: theme.colors.textSoft,
        fontSize: 11,
        marginTop: 10,
        textAlign: 'center',
    },
});

export default WalletScreen;
