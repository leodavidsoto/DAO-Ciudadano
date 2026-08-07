/**
 * API Service - Connect to DAO Ciudadana Backend
 *
 * Request/response shapes mirror backend/app/models/schemas.py and the
 * routers under backend/app/routers/ — keep both sides in sync.
 */

import axios, { AxiosInstance } from 'axios';
import { API_BASE_URL } from '../config';
import type { RawDocumentFiles } from './nfcService';

/** Mirrors CedulaVerificationResponse in backend/app/routers/cedula.py. */
export interface CedulaVerificationResponse {
    ok: boolean;
    identity_grant: string;
    identity_grant_expires_in: number;
    /** The JWT that POST /membership/mint requires and burns. */
    membership_grant: string;
    membership_grant_expires_in: number;
    assurance_level: string;
    verification: Record<string, unknown>;
}

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

    /**
     * POST /auth/cedula/verify — the real civil path (backend routers/cedula.py).
     *
     * Sends the raw chip files, not this device's verdict: the server repeats
     * passive authentication against its own CSCA trust store and only then
     * issues grants. No wallet session is required yet — the grants are
     * redeemed later, once SIWE binds them to an address.
     */
    async verifyCedula(files: RawDocumentFiles) {
        const response = await this.client.post('/auth/cedula/verify', {
            sod: files.sod,
            data_groups: { '1': files.dg1, '2': files.dg2 },
        });
        return response.data as CedulaVerificationResponse;
    }

    // Membership endpoints

    /**
     * POST /membership/mint — needs the SIWE session AND a membership grant.
     *
     * `doc_hash` and `assurance_level` are gone on purpose (AUDIT P-4): both
     * were client self-assertions. They now come from inside the grant, which
     * the server signed at the end of a real civil flow.
     */
    async mintSBT(data: { walletAddress: string; membershipGrant: string }) {
        const response = await this.client.post('/membership/mint', {
            wallet_address: data.walletAddress,
            membership_grant: data.membershipGrant,
        });
        return response.data as {
            ok: boolean;
            token_id?: number | null;
            tx_hash?: string | null;
            assurance_level?: string | null;
            error?: string | null;
        };
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
