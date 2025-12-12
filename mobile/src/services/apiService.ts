/**
 * API Service - Connect to DAO Ciudadana Backend
 */

import axios, { AxiosInstance } from 'axios';

const API_BASE_URL = 'https://dao-ciudadana-api.onrender.com/api';

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

        // Add auth interceptor
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

    // Auth endpoints
    async register(data: {
        rut: string;
        firstName: string;
        lastName: string;
        email: string;
    }) {
        const response = await this.client.post('/auth/register', data);
        return response.data;
    }

    async login(rut: string, password?: string) {
        const response = await this.client.post('/auth/login', { rut, password });
        if (response.data.token) {
            this.setToken(response.data.token);
        }
        return response.data;
    }

    // NFC verification
    async verifyNFC(data: {
        serialNumber: string;
        documentHash: string;
        rut?: string;
    }) {
        const response = await this.client.post('/auth/nfc', data);
        return response.data;
    }

    // Wallet endpoints
    async connectWallet(address: string, chainId: number) {
        const response = await this.client.post('/wallet/connect', {
            address,
            chainId,
        });
        return response.data;
    }

    // Membership endpoints
    async mintSBT(data: {
        address: string;
        identityHash: string;
        assuranceLevel: string;
    }) {
        const response = await this.client.post('/membership/mint', data);
        return response.data;
    }

    async getMembershipStatus(address: string) {
        const response = await this.client.get(`/membership/status/${address}`);
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
