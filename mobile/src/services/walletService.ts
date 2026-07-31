/**
 * Wallet Service — billetera Ethereum generada en el dispositivo.
 *
 * Genera un par de llaves real (ethers.Wallet.createRandom(), BIP-39 +
 * secp256k1) y guarda la llave privada cifrada en el almacén seguro del
 * sistema operativo (Android Keystore / iOS Keychain vía
 * react-native-keychain) — nunca en AsyncStorage ni en texto plano.
 *
 * "Conectar billetera externa" (MetaMask vía WalletConnect) queda para una
 * iteración aparte; esto cubre la opción "crear billetera nueva".
 */
import { Wallet, HDNodeWallet } from 'ethers';
import * as Keychain from 'react-native-keychain';

const KEYCHAIN_SERVICE = 'dao-ciudadana-wallet';

export interface GeneratedWallet {
    address: string;
    mnemonic: string;
    privateKey: string;
}

class WalletService {
    /**
     * Genera una billetera nueva. NO la guarda todavía — el llamador debe
     * mostrarle la frase semilla al usuario y confirmar que la respaldó
     * antes de persistirla (saveWallet), igual que cualquier wallet real.
     */
    generate(): GeneratedWallet {
        const wallet: HDNodeWallet = Wallet.createRandom();
        return {
            address: wallet.address,
            mnemonic: wallet.mnemonic?.phrase ?? '',
            privateKey: wallet.privateKey,
        };
    }

    /** Guarda la llave privada en el almacén seguro del sistema operativo. */
    async saveWallet(privateKey: string, address: string): Promise<void> {
        await Keychain.setGenericPassword(address, privateKey, {
            service: KEYCHAIN_SERVICE,
            accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
        });
    }

    /** true si ya hay una billetera guardada en este dispositivo. */
    async hasWallet(): Promise<boolean> {
        const creds = await Keychain.getGenericPassword({ service: KEYCHAIN_SERVICE });
        return creds !== false;
    }

    /** Recupera la billetera guardada, o null si no hay ninguna. */
    async loadWallet(): Promise<Wallet | null> {
        const creds = await Keychain.getGenericPassword({ service: KEYCHAIN_SERVICE });
        if (!creds) return null;
        return new Wallet(creds.password);
    }

    /** Borra la billetera del dispositivo (no recuperable sin la frase semilla). */
    async deleteWallet(): Promise<void> {
        await Keychain.resetGenericPassword({ service: KEYCHAIN_SERVICE });
    }

    /**
     * Firma un mensaje SIWE con personal_sign — mismo formato que
     * eth_account.messages.encode_defunct del backend
     * (app/services/siwe_service.py), así que la firma verifica igual que
     * viniendo de MetaMask.
     */
    async signMessage(wallet: Wallet, message: string): Promise<string> {
        return wallet.signMessage(message);
    }
}

export const walletService = new WalletService();
export default walletService;
