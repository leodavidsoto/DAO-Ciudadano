/**
 * Home Screen - Welcome and options
 */

import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme } from '../styles/theme';

interface HomeScreenProps {
    navigation: any;
}

const HomeScreen: React.FC<HomeScreenProps> = ({ navigation }) => {
    return (
        <SafeAreaView style={styles.container}>
            {/* Logo/Header */}
            <View style={styles.header}>
                <View style={styles.logoContainer}>
                    <Text style={styles.logoText}>DAO</Text>
                    <Text style={styles.logoSubtext}>CIUDADANA</Text>
                </View>
                <Text style={styles.tagline}>
                    Terminal de Autenticación Criptográfica Nacional
                </Text>
            </View>

            {/* Main Content */}
            <View style={styles.content}>
                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🪪</Text>
                    <View style={styles.featureTextContainer}>
                        <Text style={styles.featureTitle}>Autenticación eMRTD Segura</Text>
                        <Text style={styles.featureDesc}>
                            Verificación criptográfica del chip de tu cédula nacional (PACE + Autenticación Pasiva).
                        </Text>
                    </View>
                </View>

                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🔗</Text>
                    <View style={styles.featureTextContainer}>
                        <Text style={styles.featureTitle}>Generación ZK Local</Text>
                        <Text style={styles.featureDesc}>
                            Las pruebas Zero-Knowledge se computan íntegramente en tu dispositivo. El Estado no rastrea tu actividad.
                        </Text>
                    </View>
                </View>

                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🗳️</Text>
                    <View style={styles.featureTextContainer}>
                        <Text style={styles.featureTitle}>Gobernanza Anónima</Text>
                        <Text style={styles.featureDesc}>
                            Voto electrónico inviolable con pruebas MACI integradas.
                        </Text>
                    </View>
                </View>
            </View>

            {/* Action Buttons */}
            <View style={styles.buttonContainer}>
                <TouchableOpacity
                    style={styles.primaryButton}
                    onPress={() => navigation.navigate('Scan')}
                >
                    <Text style={styles.primaryButtonText}>INICIAR VERIFICACIÓN NFC</Text>
                </TouchableOpacity>

                <TouchableOpacity
                    style={styles.secondaryButton}
                    onPress={() => navigation.navigate('Wallet')}
                >
                    <Text style={styles.secondaryButtonText}>ABRIR BÓVEDA DE CREDENCIALES</Text>
                </TouchableOpacity>
            </View>

            {/* Footer */}
            <View style={styles.footer}>
                <Text style={styles.footerText}>
                    VERIFICADO POR EL REGISTRO CIVIL DE CHILE
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
        alignItems: 'center',
        paddingTop: 40,
        paddingBottom: 30,
    },
    logoContainer: {
        alignItems: 'center',
        marginBottom: 16,
    },
    logoText: {
        ...theme.typography.title,
        fontSize: 48,
        letterSpacing: 2,
    },
    logoSubtext: {
        ...theme.typography.title,
        color: theme.colors.danger,
        fontSize: 18,
        letterSpacing: 1,
        marginTop: -5,
    },
    tagline: {
        ...theme.typography.caption,
        textAlign: 'center',
    },
    content: {
        flex: 1,
        paddingHorizontal: 20,
    },
    featureCard: {
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radius.md,
        padding: 16,
        marginBottom: 12,
        borderWidth: 1,
        borderColor: theme.colors.borderLight,
        flexDirection: 'row',
        alignItems: 'center',
        ...theme.shadows.light,
    },
    featureIcon: {
        fontSize: 24,
        marginRight: 12,
    },
    featureTextContainer: {
        flex: 1,
    },
    featureTitle: {
        ...theme.typography.body,
        fontWeight: 'bold',
        marginBottom: 4,
    },
    featureDesc: {
        ...theme.typography.caption,
    },
    buttonContainer: {
        padding: 20,
        gap: 12,
    },
    primaryButton: {
        backgroundColor: theme.colors.primary,
        paddingVertical: 18,
        borderRadius: theme.radius.md,
        alignItems: 'center',
        ...theme.shadows.light,
    },
    primaryButtonText: {
        color: '#FFFFFF',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 0.5,
    },
    secondaryButton: {
        backgroundColor: theme.colors.surface,
        paddingVertical: 16,
        borderRadius: theme.radius.md,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: theme.colors.borderDark,
    },
    secondaryButtonText: {
        color: theme.colors.primary,
        fontSize: 14,
        fontWeight: '600',
        letterSpacing: 0.5,
    },
    footer: {
        padding: 20,
        alignItems: 'center',
    },
    footerText: {
        ...theme.typography.caption,
    },
});

export default HomeScreen;
