/**
 * Home Screen - Welcome and options
 */

import React from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

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
                    Identidad Digital Soberana en Blockchain
                </Text>
            </View>

            {/* Main Content */}
            <View style={styles.content}>
                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🪪</Text>
                    <Text style={styles.featureTitle}>Verificación NFC</Text>
                    <Text style={styles.featureDesc}>
                        Lee el chip de tu cédula chilena para verificar tu identidad de forma segura
                    </Text>
                </View>

                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🔗</Text>
                    <Text style={styles.featureTitle}>Blockchain</Text>
                    <Text style={styles.featureDesc}>
                        Tu identidad se almacena como un token Soulbound en Ethereum
                    </Text>
                </View>

                <View style={styles.featureCard}>
                    <Text style={styles.featureIcon}>🗳️</Text>
                    <Text style={styles.featureTitle}>Gobernanza</Text>
                    <Text style={styles.featureDesc}>
                        Participa en decisiones democráticas con voto verificado
                    </Text>
                </View>
            </View>

            {/* Action Buttons */}
            <View style={styles.buttonContainer}>
                <TouchableOpacity
                    style={styles.primaryButton}
                    onPress={() => navigation.navigate('Scan')}
                >
                    <Text style={styles.primaryButtonText}>ESCANEAR CÉDULA</Text>
                </TouchableOpacity>

                <TouchableOpacity
                    style={styles.secondaryButton}
                    onPress={() => navigation.navigate('Wallet')}
                >
                    <Text style={styles.secondaryButtonText}>YA TENGO MEMBRESÍA</Text>
                </TouchableOpacity>
            </View>

            {/* Footer */}
            <View style={styles.footer}>
                <Text style={styles.footerText}>
                    Powered by Ethereum • Sepolia Testnet
                </Text>
            </View>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#0a0a1a',
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
        fontSize: 48,
        fontWeight: 'bold',
        color: '#00FFFF',
        letterSpacing: 8,
    },
    logoSubtext: {
        fontSize: 18,
        color: '#FF00FF',
        letterSpacing: 6,
        marginTop: -5,
    },
    tagline: {
        fontSize: 12,
        color: '#666',
        textAlign: 'center',
    },
    content: {
        flex: 1,
        paddingHorizontal: 20,
    },
    featureCard: {
        backgroundColor: '#0a0a2a',
        borderRadius: 16,
        padding: 20,
        marginBottom: 12,
        borderWidth: 1,
        borderColor: '#ffffff10',
        flexDirection: 'row',
        alignItems: 'center',
    },
    featureIcon: {
        fontSize: 32,
        marginRight: 16,
    },
    featureTitle: {
        flex: 1,
        fontSize: 16,
        fontWeight: 'bold',
        color: '#fff',
    },
    featureDesc: {
        flex: 2,
        fontSize: 12,
        color: '#888',
    },
    buttonContainer: {
        padding: 20,
        gap: 12,
    },
    primaryButton: {
        backgroundColor: '#00FFFF',
        paddingVertical: 18,
        borderRadius: 14,
        alignItems: 'center',
    },
    primaryButtonText: {
        color: '#000',
        fontSize: 16,
        fontWeight: 'bold',
        letterSpacing: 1,
    },
    secondaryButton: {
        backgroundColor: 'transparent',
        paddingVertical: 16,
        borderRadius: 14,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: '#00FFFF50',
    },
    secondaryButtonText: {
        color: '#00FFFF',
        fontSize: 14,
        fontWeight: '600',
        letterSpacing: 1,
    },
    footer: {
        padding: 20,
        alignItems: 'center',
    },
    footerText: {
        fontSize: 10,
        color: '#444',
    },
});

export default HomeScreen;
