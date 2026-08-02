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

// MACI messages use a separate bearer-free transport boundary. In particular,
// this instance never receives the SIWE token interceptor below. Avoiding that
// direct identifier is necessary but not sufficient for network unlinkability;
// the backend must add an anonymous eligibility proof and privacy-preserving
// relay before enabling `private_voting`.
const anonymousMaciApi = axios.create({
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
    // The Safe SDK is loaded only at mint time. Pimlico credentials never
    // enter the browser: the authenticated backend prepares/sponsors the exact
    // operation, then the citizen signs every final v0.7 field locally.
    mintWithProof: async (proof) => {
        const { mintMembershipWithSafe } = await import('./erc4337');
        return mintMembershipWithSafe({
            proof,
            getConfig: () => erc4337API.getConfig(),
            prepareMint: (payload) => erc4337API.prepareMint(payload),
            submitMint: (payload) => erc4337API.submitMint(payload),
            getOperation: (userOperationHash) =>
                erc4337API.getOperation(userOperationHash),
            timeoutMs: ONCHAIN_OPERATION_TIMEOUT_MS,
        });
    },
    verify: (tokenId) => api.get(`/membership/verify/${tokenId}`),
    getByWallet: (address) => api.get(`/membership/member/${address}`),
};

// Authenticated policy/sponsorship proxy. The browser deliberately has no
// REACT_APP_PIMLICO_* secret and never talks to a privileged bundler endpoint.
export const erc4337API = {
    getConfig: () => api.get('/erc4337/config'),
    prepareMint: (payload) => api.post('/erc4337/prepare-mint', payload, {
        timeout: ONCHAIN_OPERATION_TIMEOUT_MS,
    }),
    submitMint: (payload) => api.post('/erc4337/submit-mint', payload, {
        timeout: ONCHAIN_OPERATION_TIMEOUT_MS,
    }),
    getOperation: (userOperationHash) =>
        api.get(`/erc4337/operations/${encodeURIComponent(userOperationHash)}`),
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

const isCanonicalDecimal = (value) =>
    typeof value === 'string' && /^(?:0|[1-9][0-9]*)$/.test(value);
const MACI_PROTOCOL_VERSION = 'maci-v2.5.0';
const MACI_FIELD_MODULUS = BigInt(
    '21888242871839275222246405745257275088548364400416034343698204186575808495617'
);
const MACI_UINT50_LIMIT = 1n << 50n;
const isCanonicalFieldElement = (value) =>
    isCanonicalDecimal(value) && BigInt(value) < MACI_FIELD_MODULUS;

/**
 * Whitelist the public MACI wire message. Choice, wallet, command, signature,
 * shared key and private keys are intentionally impossible to serialize here.
 */
export const buildEncryptedBallotPayload = ({
    protocolVersion,
    proposalId,
    pollId,
    message,
    encryptionPublicKey,
    coordinatorKeyHash,
    idempotencyKey,
}) => {
    const ciphertext = message?.data;
    if (!Array.isArray(ciphertext) || ciphertext.length !== 10 ||
        !ciphertext.every(isCanonicalFieldElement)) {
        throw new Error('El mensaje MACI debe contener diez elementos decimales.');
    }
    if (
        !encryptionPublicKey ||
        !isCanonicalFieldElement(encryptionPublicKey.x) ||
        !isCanonicalFieldElement(encryptionPublicKey.y)
    ) {
        throw new Error('La llave pública efímera MACI no es válida.');
    }
    if (typeof proposalId !== 'string' || !proposalId.trim()) {
        throw new Error('La papeleta MACI no identifica una propuesta.');
    }
    if (
        !isCanonicalDecimal(String(pollId)) ||
        BigInt(String(pollId)) >= MACI_UINT50_LIMIT
    ) {
        throw new Error('La papeleta MACI no identifica un poll válido.');
    }
    if (protocolVersion !== MACI_PROTOCOL_VERSION) {
        throw new Error('La versión MACI no es compatible.');
    }
    if (!/^0x[0-9a-fA-F]{64}$/.test(coordinatorKeyHash || '')) {
        throw new Error('El hash de la llave coordinadora no es válido.');
    }
    if (typeof idempotencyKey !== 'string' || !/^[a-zA-Z0-9-]{16,80}$/.test(idempotencyKey)) {
        throw new Error('La clave de idempotencia de la papeleta no es válida.');
    }

    return {
        protocol_version: protocolVersion,
        proposal_id: proposalId,
        poll_id: String(pollId),
        message: { data: [...ciphertext] },
        encryption_public_key: {
            x: encryptionPublicKey.x,
            y: encryptionPublicKey.y,
        },
        coordinator_key_hash: coordinatorKeyHash,
        idempotency_key: idempotencyKey,
    };
};

export const maciAPI = {
    getStatus: () => api.get('/maci/status'),
    registerKey: (walletAddress, publicKey) => api.post('/maci/keys', {
        wallet_address: walletAddress,
        public_key: { x: publicKey.x, y: publicKey.y },
    }),
    getVotingConfig: (proposalId) =>
        api.get(`/maci/proposals/${encodeURIComponent(proposalId)}/poll`),
    // Deliberately una instancia sin Authorization/SIWE. The backend contract
    // must use an anonymous eligibility proof and a rate-limited relay.
    submitEncryptedBallot: (ballot) => {
        const payload = buildEncryptedBallotPayload(ballot);
        return anonymousMaciApi.post(
            `/maci/polls/${encodeURIComponent(payload.poll_id)}/messages`,
            payload
        );
    },
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
