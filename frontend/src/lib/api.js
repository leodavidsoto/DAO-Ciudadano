/**
 * API Service
 * Centralized API communication layer
 */
import axios from 'axios';
import {
    getCsrfToken,
    invalidateSession,
    setCsrfToken,
} from './session';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
const API_BASE = `${BACKEND_URL}/api`;
const ONCHAIN_OPERATION_TIMEOUT_MS = 120000;
export const CSRF_HEADER_NAME = 'X-CSRF-Token';
const SAFE_HTTP_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

// All non-anonymous web requests use the HttpOnly SIWE cookie. Automatic
// Axios XSRF cookie reading is disabled because production runs the frontend
// and API on different origins; /wallet/session returns the CSRF value that we
// keep in memory and attach explicitly below.
export const api = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
    timeout: 30000,
    withCredentials: true,
    withXSRFToken: false,
});

// Encrypted MACI messages are the deliberate exception to credentialed
// transport. Attaching the session cookie here would link a supposedly
// anonymous ballot to the citizen's SIWE session.
export const anonymousMaciApi = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
    timeout: 30000,
    withCredentials: false,
    withXSRFToken: false,
});

const removeAuthorizationHeader = (headers) => {
    if (!headers) return;
    if (typeof headers.delete === 'function') {
        headers.delete('Authorization');
        return;
    }
    delete headers.Authorization;
    delete headers.authorization;
};

const setRequestHeader = (headers, name, value) => {
    if (typeof headers?.set === 'function') {
        headers.set(name, value);
    } else if (headers) {
        headers[name] = value;
    }
};

const captureCsrfToken = (response) => {
    const bodyHasToken = Object.prototype.hasOwnProperty.call(
        response?.data || {},
        'csrf_token'
    );
    const responseHeader = typeof response?.headers?.get === 'function'
        ? response.headers.get(CSRF_HEADER_NAME)
        : response?.headers?.['x-csrf-token'];
    const candidate = bodyHasToken ? response.data.csrf_token : responseHeader;
    if (candidate !== undefined && candidate !== null) {
        setCsrfToken(candidate);
    }
};

api.interceptors.request.use(
    (config) => {
        // A stale caller-provided bearer must never override the current
        // cookie session. The mobile app uses its own bearer-aware client.
        removeAuthorizationHeader(config.headers);

        const method = (config.method || 'GET').toUpperCase();
        const csrfToken = getCsrfToken();
        if (!SAFE_HTTP_METHODS.has(method) && csrfToken) {
            setRequestHeader(config.headers, CSRF_HEADER_NAME, csrfToken);
        }
        return config;
    },
    (error) => Promise.reject(error)
);

// Response interceptor
api.interceptors.response.use(
    (response) => {
        captureCsrfToken(response);
        return response;
    },
    (error) => {
        if (error.response?.status === 401) {
            invalidateSession('unauthorized');
        } else {
            console.error('API Error:', error.response?.data || error.message);
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
    challenge: (address) => api.post('/wallet/challenge', { address }),
    verify: (address, nonce, signature) =>
        api.post('/wallet/verify', {
            address,
            nonce,
            signature,
            session_transport: 'cookie',
        }),
    session: () => api.get('/wallet/session'),
    logout: () => api.post('/wallet/logout'),
};

// === Membership API ===
export const membershipAPI = {
    // The Safe SDK is loaded only at mint time. Pimlico credentials never
    // enter the browser: the authenticated backend prepares/sponsors the exact
    // operation, then the citizen signs every final v0.7 field locally.
    mintWithProof: async (proof, eip1193Provider, onProgress) => {
        const { mintMembershipWithSafe } = await import('./erc4337');
        return mintMembershipWithSafe({
            proof,
            provider: eip1193Provider,
            onProgress,
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
    getBallotSchema: () => api.get('/governance/elections/ballot-schema'),
    vote: (electionId, voterAddress, candidateAddress, nonce, signature) =>
        api.post(`/governance/elections/${electionId}/vote`, {
            voter_address: voterAddress,
            candidate_address: candidateAddress,
            nonce,
            signature,
        }),
    results: (electionId) => api.get(`/governance/elections/${electionId}/results`),

    // Elected representatives with an active term
    representatives: () => api.get('/governance/representatives'),
};

export default api;
