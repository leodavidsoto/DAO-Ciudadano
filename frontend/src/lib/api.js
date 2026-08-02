/**
 * API Service
 * Centralized API communication layer
 */
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
const API_BASE = `${BACKEND_URL}/api`;
const ONCHAIN_OPERATION_TIMEOUT_MS = 120000;

// Create axios instance with defaults
const api = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
    timeout: 30000,
});

// Request interceptor
api.interceptors.request.use(
    (config) => {
        // Add auth token if available
        const token = localStorage.getItem('auth_token');
        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Response interceptor
api.interceptors.response.use(
    (response) => response,
    (error) => {
        console.error('API Error:', error.response?.data || error.message);
        if (error.response?.status === 401) {
            // El token de sesión (SIWE) expiró o es inválido -- lo limpiamos
            // para que el próximo connect() vuelva a pedir firma en vez de
            // reintentar para siempre con un token muerto.
            localStorage.removeItem('auth_token');
            localStorage.removeItem('auth_address');
        }
        return Promise.reject(error);
    }
);

export const buildIdentityCredentialRequest = ({
    walletAddress,
    identityCommitment,
    membershipScope,
    membershipContract,
    chainId,
    identityGrant,
}) => ({
    wallet_address: walletAddress,
    identity_commitment: identityCommitment,
    membership_scope: membershipScope,
    membership_contract: membershipContract,
    chain_id: chainId,
    identity_grant: identityGrant,
});

// === Auth API ===
export const authAPI = {
    claveUnica: (rut) => api.post('/auth/clave-unica', { rut }),
    nfc: () => api.post('/auth/nfc'),
    liveness: (file) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('/auth/liveness', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            timeout: 60000, // Longer timeout for AI processing
        });
    },
    // RUT + Email registration
    register: (rut, email, nombre, apellido) =>
        api.post('/auth/register', { rut, email, nombre, apellido }),
    login: (rut, email) =>
        api.post('/auth/login', { rut, email }),
    // Post-SIWE enrollment. Only the public wallet-bound commitment crosses
    // this boundary; the identity secret remains in the browser.
    issueIdentityCredential: ({
        walletAddress,
        identityCommitment,
        membershipScope,
        membershipContract,
        chainId,
        identityGrant,
    }) =>
        api.post(
            '/auth/identity-credential',
            buildIdentityCredentialRequest({
                walletAddress,
                identityCommitment,
                membershipScope,
                membershipContract,
                chainId,
                identityGrant,
            }),
            { timeout: ONCHAIN_OPERATION_TIMEOUT_MS }
        ),
};

// === Wallet API ===
export const walletAPI = {
    // Sesión de wallet real (SIWE, ver services/siwe_service.py en el backend).
    challenge: (address) => api.post('/wallet/challenge', { address }),
    verify: (address, nonce, signature) =>
        api.post('/wallet/verify', { address, nonce, signature }),
};

// === Membership API ===
export const membershipAPI = {
    // Exact relayer boundary for DAOCiudadanaSBT.mintMembership. The signed
    // identity claim, Merkle path, local secret and redundant public signals
    // must never cross this boundary.
    mintWithProof: (proof) =>
        api.post('/membership/mint-zk', buildZkMintPayload(proof), {
            timeout: ONCHAIN_OPERATION_TIMEOUT_MS,
        }),
    verify: (tokenId) => api.get(`/membership/verify/${tokenId}`),
    getByWallet: (address) => api.get(`/membership/member/${address}`),
};

export const buildZkMintPayload = ({
    walletAddress,
    pA,
    pB,
    pC,
    nullifierHash,
    identityRoot,
}) => ({
    wallet_address: walletAddress,
    pA,
    pB,
    pC,
    nullifier_hash: nullifierHash,
    identity_root: identityRoot,
});

// === Dashboard API ===
export const dashboardAPI = {
    getStats: () => api.get('/dashboard/stats'),
    getActivity: (limit = 10) => api.get(`/dashboard/activity?limit=${limit}`),
};

// === Governance API ===
export const governanceAPI = {
    // Proposals — los filtros van como `params` para que axios los codifique;
    // interpolarlos en la URL rompe cualquier valor con `&`, `#` o espacios.
    getProposals: (status = null) =>
        api.get('/governance/proposals', { params: status ? { status } : {} }),
    getProposal: (id) => api.get(`/governance/proposals/${id}`),
    createProposal: (title, description, category, creatorAddress, durationDays = 7) =>
        api.post('/governance/proposals', {
            title,
            description,
            category,
            creator_address: creatorAddress,
            duration_days: durationDays,
        }),

    // Voting
    getBallotSchema: () => api.get('/governance/ballot-schema'),
    getBallots: (proposalId) => api.get(`/governance/proposals/${proposalId}/ballots`),
    vote: (proposalId, voterAddress, vote, nonce, signature) =>
        api.post('/governance/vote', {
            proposal_id: proposalId,
            voter_address: voterAddress,
            vote,
            nonce,
            signature,
        }),

    // Delegation
    delegate: (delegatorAddress, delegateAddress) =>
        api.post('/governance/delegate', {
            delegator_address: delegatorAddress,
            delegate_address: delegateAddress,
        }),
    revokeDelegation: (address) => api.delete(`/governance/delegate/${address}`),
    getDelegation: (address) => api.get(`/governance/delegate/${address}`),
    getDelegators: (delegateAddress) => api.get(`/governance/delegations/${delegateAddress}`),

    // Treasury
    getTreasury: () => api.get('/governance/treasury'),
    getTreasuryTransactions: (limit = 20, category = null) =>
        api.get('/governance/treasury/transactions', {
            params: { limit, ...(category ? { category } : {}) },
        }),
    getTreasuryAnalytics: () => api.get('/governance/treasury/analytics'),

    // Stats
    getStats: () => api.get('/governance/stats'),
};

// === Elections API ===
export const electionsAPI = {
    list: (status = null) =>
        api.get('/governance/elections', { params: status ? { status } : {} }),
    get: (id) => api.get(`/governance/elections/${id}`),
    create: ({ title, description, seats, nominationsDays, votingDays, termMonths, creatorAddress }) =>
        api.post('/governance/elections', {
            title,
            description,
            seats,
            nominations_days: nominationsDays,
            voting_days: votingDays,
            term_months: termMonths,
            creator_address: creatorAddress,
        }),

    // Candidacies
    listCandidacies: (electionId) =>
        api.get(`/governance/elections/${electionId}/candidacies`),
    runForOffice: (electionId, candidateAddress, statement) =>
        api.post(`/governance/elections/${electionId}/candidacies`, {
            candidate_address: candidateAddress,
            statement,
        }),

    // Voting
    vote: (electionId, voterAddress, candidateAddress) =>
        api.post(`/governance/elections/${electionId}/vote`, {
            voter_address: voterAddress,
            candidate_address: candidateAddress,
        }),
    results: (electionId) => api.get(`/governance/elections/${electionId}/results`),

    // Elected representatives with an active term
    representatives: () => api.get('/governance/representatives'),
};

export default api;
