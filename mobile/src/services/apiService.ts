/**
 * API Service - Connect to DAO Ciudadana Backend
 *
 * Request/response shapes mirror backend/app/models/schemas.py and the
 * routers under backend/app/routers/ — keep both sides in sync.
 */

import axios, { AxiosInstance } from 'axios';
import { API_BASE_URL } from '../config';

class ApiService {
    private client: AxiosInstance;
    private token: string | null = null;

    constructor() {
        this.client = axios.create({
            baseURL: API_BASE_URL,
            timeout: 30000,
            headers: {
                'Content-Type': 'application/json',
            },
        });

        // Bearer token support for the JWT returned by walletVerify (SIWE).
        this.client.interceptors.request.use((config) => {
            if (this.token) {
                config.headers.Authorization = `Bearer ${this.token}`;
            }
            return config;
        });
    }

    setToken(token: string) {
        this.token = token;
    }

    // Wallet session (SIWE) endpoints

    /** POST /wallet/challenge — pide un desafío de un solo uso para firmar. */
    async walletChallenge(address: string) {
        const response = await this.client.post('/wallet/challenge', { address });
        return response.data as { message: string; nonce: string };
    }

    /** POST /wallet/verify — verifica la firma y devuelve el JWT de sesión. */
    async walletVerify(address: string, nonce: string, signature: string) {
        const response = await this.client.post('/wallet/verify', {
            address,
            nonce,
            signature,
        });
        return response.data as { token: string; address: string; expires_in: number };
    }

    // Auth endpoints

    /** POST /auth/register — expects rut, email, nombre, apellido */
    async register(data: {
        rut: string;
        nombre: string;
        apellido: string;
        email: string;
    }) {
        const response = await this.client.post('/auth/register', data);
        return response.data;
    }

    /** POST /auth/login — demo account lookup; it does not create a wallet session. */
    async login(rut: string, email: string) {
        const response = await this.client.post('/auth/login', { rut, email });
        return response.data;
    }

    /** POST /auth/nfc — sends the chip serial read from the card (demo backend) */
    async verifyNFC(chipSerial?: string) {
        const response = await this.client.post(
            '/auth/nfc',
            chipSerial ? { chip_serial: chipSerial } : {},
        );
        return response.data;
    }

    // Membership endpoints

    /** POST /membership/mint — off-chain demo registration, tx_hash is null */
    async mintSBT(data: {
        walletAddress: string;
        docHash: string;
        assuranceLevel: string;
    }) {
        const response = await this.client.post('/membership/mint', {
            wallet_address: data.walletAddress,
            doc_hash: data.docHash,
            assurance_level: data.assuranceLevel,
        });
        return response.data;
    }

    /** GET /membership/member/{address} — { found, member? } */
    async getMembershipStatus(address: string) {
        const response = await this.client.get(`/membership/member/${address}`);
        return response.data;
    }

    // Health check
    async healthCheck() {
        const response = await this.client.get('/');
        return response.data;
    }
}

export const apiService = new ApiService();
export default apiService;
