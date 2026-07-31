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
 * Si se llega desde el flujo NFC (Home -> Scan -> Success -> Wallet), los
 * datos del chip vienen en route.params y se usan para mintear la
 * membresía automáticamente en cuanto la sesión de wallet queda firmada. Si
 * se llega directo desde "YA TENGO MEMBRESÍA" en Home, route.params viene
 * vacío y la pantalla se limita a conectar/crear la wallet y mostrar el
 * estado de membresía existente.
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
import { ChileanIDData } from '../services/nfcService';

// SHA-256 cargado en diferido, mismo patrón que nfcService.ts: no debe
// tumbar la carga de la app si el módulo nativo falla en inicializar.
let _crypto: any = null;
function getCrypto() {
    if (!_crypto) {
        try {
            _crypto = require('react-native-quick-crypto');
        } catch (e) {
            _crypto = null;
        }
    }
    return _crypto;
}

/** doc_hash determinístico a partir del serial NFC leído (el backend lo
 * vuelve a peppear con HMAC antes de usarlo on-chain, ver
 * app/core/identity.py:document_identity_hash_hex — acá solo hace falta
 * un valor no vacío y estable). */
function hashSerial(serialNumber: string): string {
    const crypto = getCrypto();
    if (!crypto) return `0x${Buffer.from(serialNumber).toString('hex')}`;
    const digest = crypto.createHash('sha256').update(serialNumber).digest('hex');
    return `0x${digest}`;
}

interface MemberInfo {
    token_id: number;
    wallet_address: string;
    assurance_level: string;
    status: string;
    tx_hash?: string | null;
}

interface WalletScreenProps {
    navigation: any;
    route?: {
        params?: {
            idData?: ChileanIDData;
            serialNumber?: string;
        };
    };
}

type ScreenState =
    | 'checking'
    | 'choose'
    | 'backup'
    | 'signing-in'
    | 'minting'
    | 'ready'
    | 'lookup';

const ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;

const WalletScreen: React.FC<WalletScreenProps> = ({ navigation, route }) => {
    const idData = route?.params?.idData;
    const serialNumber = route?.params?.serialNumber;

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

            if (idData && serialNumber) {
                setState('minting');
                const mintResult = await apiService.mintSBT({
                    walletAddress: wallet.address,
                    docHash: hashSerial(serialNumber),
                    assuranceLevel: 'AL2',
                });
                if (mintResult.ok) {
                    setMember({
                        token_id: mintResult.token_id,
                        wallet_address: wallet.address,
                        assurance_level: 'AL2',
                        status: 'active',
                        tx_hash: mintResult.tx_hash,
                    });
                } else {
                    setError(mintResult.error || 'No se pudo registrar la membresía');
                }
            }
            setState('ready');
        } catch (e: any) {
            setError(
                e?.response?.data?.detail || e?.message || 'Error estableciendo la sesión de wallet',
            );
            setState('ready');
        }
    }, [idData, serialNumber]);

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
            } catch (e) {
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
        } catch (e) {
            setError('No se pudo consultar el servidor. Verifica tu conexión.');
        } finally {
            setLookupLoading(false);
        }
    };

    // === Render: comprobando billetera existente ===
    if (state === 'checking' || state === 'signing-in' || state === 'minting') {
        const label = state === 'checking'
            ? 'VERIFICANDO BILLETERA...'
            : state === 'signing-in'
                ? 'FIRMANDO SESIÓN DE WALLET...'
                : 'REGISTRANDO MEMBRESÍA...';
        return (
            <SafeAreaView style={styles.container}>
                <View style={styles.centered}>
                    <ActivityIndicator size="large" color="#00FFFF" />
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
                    <Text style={styles.title}>TU BILLETERA DIGITAL</Text>
                    <Text style={styles.subtitle}>
                        Necesitas una wallet Ethereum para obtener tu membresía DAO
                    </Text>

                    <TouchableOpacity style={styles.button} onPress={handleCreateWallet}>
                        <Text style={styles.buttonText}>CREAR BILLETERA NUEVA</Text>
                    </TouchableOpacity>
                    <Text style={styles.hint}>
                        Genera una wallet en este dispositivo. Vas a ver una frase de respaldo
                        de 12 palabras una sola vez — guárdala en un lugar seguro.
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
                    <Text style={styles.title}>TU FRASE DE RESPALDO</Text>
                    <View style={styles.warningBox}>
                        <Text style={styles.warningText}>
                            Escribe estas 12 palabras en papel y guárdalas en un lugar seguro.
                            Son la ÚNICA forma de recuperar tu billetera. Nadie de DAO Ciudadana
                            puede recuperarlas por ti si las pierdes.
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
                    <Text style={styles.title}>BILLETERA CONECTADA</Text>
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
                            <Text style={styles.resultTitle}>MEMBRESÍA ACTIVA</Text>
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
                            {member.tx_hash && (
                                <View style={styles.dataRow}>
                                    <Text style={styles.dataLabel}>Tx:</Text>
                                    <Text style={styles.dataValueSmall}>{member.tx_hash}</Text>
                                </View>
                            )}
                        </View>
                    ) : (
                        <View style={styles.emptyCard}>
                            <Text style={styles.emptyTitle}>SIN MEMBRESÍA TODAVÍA</Text>
                            <Text style={styles.emptyText}>
                                {idData
                                    ? 'No se pudo completar el registro automáticamente.'
                                    : 'Escanea tu cédula para obtener tu membresía con esta wallet.'}
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

                {lookupSearched && lookupMember && (
                    <View style={styles.resultCard}>
                        <Text style={styles.resultTitle}>MEMBRESÍA ENCONTRADA</Text>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Token ID:</Text>
                            <Text style={styles.dataValue}>#{lookupMember.token_id}</Text>
                        </View>
                        <View style={styles.dataRow}>
                            <Text style={styles.dataLabel}>Nivel:</Text>
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
    container: { flex: 1, backgroundColor: '#0a0a1a' },
    content: { padding: 20 },
    centered: { flex: 1, justifyContent: 'center', alignItems: 'center' },
    loadingText: { color: '#00FFFF', marginTop: 16, fontSize: 13, letterSpacing: 1 },
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
        marginTop: 12,
    },
    buttonDisabled: { opacity: 0.4 },
    buttonDisabledOutline: {
        borderWidth: 1,
        borderColor: '#ffffff20',
        paddingVertical: 16,
        borderRadius: 12,
        alignItems: 'center',
        marginTop: 12,
    },
    buttonDisabledText: {
        color: '#666',
        fontSize: 15,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    buttonText: {
        color: '#000',
        fontSize: 15,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    hint: {
        fontSize: 11,
        color: '#666',
        marginTop: 8,
        marginBottom: 8,
        textAlign: 'center',
    },
    linkButton: { marginTop: 24, alignItems: 'center' },
    linkButtonText: { color: '#00FFFF', fontSize: 13, textDecorationLine: 'underline' },
    errorBox: {
        marginTop: 16,
        padding: 12,
        backgroundColor: '#FF073A15',
        borderRadius: 8,
        borderWidth: 1,
        borderColor: '#FF073A50',
    },
    errorText: { color: '#FF6B81', fontSize: 13 },
    warningBox: {
        backgroundColor: '#FFA50015',
        borderWidth: 1,
        borderColor: '#FFA50050',
        borderRadius: 12,
        padding: 16,
        marginBottom: 16,
    },
    warningText: { color: '#FFCC80', fontSize: 13, lineHeight: 19 },
    mnemonicBox: {
        backgroundColor: '#0a0a2a',
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#00FFFF30',
        padding: 20,
        marginBottom: 16,
    },
    mnemonicText: {
        color: '#00FFFF',
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
        borderColor: '#00FFFF60',
        marginRight: 12,
        justifyContent: 'center',
        alignItems: 'center',
    },
    checkboxChecked: { backgroundColor: '#00FFFF', borderColor: '#00FFFF' },
    checkboxMark: { color: '#000', fontWeight: 'bold', fontSize: 14 },
    checkboxLabel: { color: '#ccc', fontSize: 13, flex: 1 },
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
    dataLabel: { color: '#666', fontSize: 14 },
    dataValue: { color: '#fff', fontSize: 14, fontWeight: '600' },
    dataValueSmall: {
        color: '#fff',
        fontSize: 11,
        fontWeight: '600',
        flexShrink: 1,
        textAlign: 'right',
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
    emptyTitle: { fontSize: 13, color: '#888', letterSpacing: 1, marginBottom: 8 },
    emptyText: { fontSize: 13, color: '#666', textAlign: 'center', marginBottom: 16 },
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
