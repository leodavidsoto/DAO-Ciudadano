/**
 * Browser-side Groth16 client for MembershipEligibility(25).
 *
 * The issuer returns a signed, wallet-bound identity credential containing a
 * Merkle witness. The signature is retained only as provenance for that
 * credential; it is never sent to the mint endpoint and is not confused with
 * the SIWE signature that only proves control of a wallet.
 *
 * Circuit boundary (fixed order):
 *   public  [identityRoot, nullifierHash, recipient, scope]
 *   private [identitySecret, pathElements[25], pathIndices[25]]
 *
 * The identity secret is generated and stored locally. It must first be used
 * to create the issuer commitment with `deriveIdentityCommitment`; the issuer
 * then inserts that commitment in an approved tree and returns the witness.
 */
import { BrowserProvider, Contract, getAddress, verifyMessage } from 'ethers';

export const BN254_SCALAR_FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;
export const BN254_BASE_FIELD =
    21888242871839275222246405745257275088696311157297823662689037894645226208583n;
export const IDENTITY_TREE_DEPTH = 25;

const publicBase = String(process.env.PUBLIC_URL || '').replace(/\/$/, '');
export const ZK_ARTIFACT_URLS = Object.freeze({
    wasm:
        process.env.REACT_APP_ZK_WASM_URL ||
        `${publicBase}/zk/verify_identity.wasm`,
    zkey:
        process.env.REACT_APP_ZK_ZKEY_URL ||
        `${publicBase}/zk/verify_identity_final.zkey`,
    verificationKey:
        process.env.REACT_APP_ZK_VKEY_URL ||
        `${publicBase}/zk/verification_key.json`,
});

const SECRET_STORAGE_KEY = 'zk_identity_secret_v2';
const IDENTITY_CREDENTIAL_DOMAIN = 'DAO Ciudadana Identity Credential v1';
const IDENTITY_ISSUER_ADDRESS =
    process.env.REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS || '';
const MEMBERSHIP_CONTRACT_ADDRESS =
    process.env.REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS || '';
const MEMBERSHIP_SCOPE_ABI = [
    'function membershipScope() view returns (uint256)',
    'function isIdentityRootApproved(uint256 identityRoot) view returns (bool)',
];
let poseidonPromise;

export class ZkNotProvisionedError extends Error {
    constructor(message, missing = []) {
        super(message);
        this.name = 'ZkNotProvisionedError';
        this.missing = missing;
    }
}

export class ZkProofError extends Error {
    constructor(message) {
        super(message);
        this.name = 'ZkProofError';
    }
}

function getLocalStorage() {
    try {
        if (!globalThis.localStorage) {
            throw new Error('localStorage is unavailable');
        }
        return globalThis.localStorage;
    } catch {
        throw new ZkProofError(
            'El almacenamiento seguro del navegador no está disponible; no se puede conservar el secreto de identidad.'
        );
    }
}

function normalizeFieldElement(value, label, { allowZero = false } = {}) {
    let normalized;
    try {
        if (
            typeof value === 'number' &&
            (!Number.isSafeInteger(value) || value < 0)
        ) {
            throw new Error('unsafe number');
        }
        if (
            !['bigint', 'number', 'string'].includes(typeof value) ||
            (typeof value === 'string' && !value.trim())
        ) {
            throw new Error('missing value');
        }
        normalized = BigInt(value);
    } catch {
        throw new ZkProofError(`${label} no es un elemento de campo válido.`);
    }

    if (normalized < 0n || normalized >= BN254_SCALAR_FIELD) {
        throw new ZkProofError(`${label} está fuera del campo escalar BN254.`);
    }
    if (!allowZero && normalized === 0n) {
        throw new ZkProofError(`${label} no puede ser cero.`);
    }
    return normalized.toString();
}

function normalizeRecipient(address) {
    try {
        const checksumAddress = getAddress(String(address || ''));
        if (BigInt(checksumAddress) === 0n) {
            throw new Error('zero address');
        }
        return {
            address: checksumAddress,
            signal: BigInt(checksumAddress).toString(),
        };
    } catch {
        throw new ZkProofError('La wallet receptora no es una dirección EVM válida.');
    }
}

function credentialValue(credential, camelCase, snakeCase) {
    return credential?.[camelCase] ?? credential?.[snakeCase];
}

/**
 * Validate and normalize the issuer credential for local-only proof creation.
 * Python backends may return snake_case; browser code may use camelCase.
 */
export function normalizeIdentityCredential(identity, recipientAddress) {
    if (!identity || typeof identity !== 'object' || Array.isArray(identity)) {
        throw new ZkProofError(
            'Falta la credencial identity firmada por el emisor.'
        );
    }

    const signature =
        identity.signature ?? identity.signedClaim ?? identity.signed_claim;
    if (typeof signature !== 'string' || !signature.trim()) {
        throw new ZkProofError(
            'La credencial identity no contiene la firma del emisor.'
        );
    }

    const recipient = normalizeRecipient(recipientAddress);
    const credentialRecipient = credentialValue(
        identity,
        'recipient',
        'wallet_address'
    );
    if (!credentialRecipient) {
        throw new ZkProofError(
            'La credencial identity no declara la wallet receptora.'
        );
    }
    const boundRecipient = normalizeRecipient(credentialRecipient);
    if (boundRecipient.address !== recipient.address) {
        throw new ZkProofError(
            'La credencial identity pertenece a otra wallet; se descartó antes de generar la prueba.'
        );
    }

    const identityRoot = normalizeFieldElement(
        credentialValue(identity, 'identityRoot', 'identity_root'),
        'La raíz de identidad'
    );
    const scope = normalizeFieldElement(
        credentialValue(identity, 'scope', 'membership_scope'),
        'El scope de membresía'
    );
    const commitment = normalizeFieldElement(
        credentialValue(identity, 'commitment', 'identity_commitment'),
        'El commitment de identidad'
    );

    const rawPathElements = credentialValue(
        identity,
        'pathElements',
        'path_elements'
    );
    const rawPathIndices = credentialValue(
        identity,
        'pathIndices',
        'path_indices'
    );
    if (
        !Array.isArray(rawPathElements) ||
        rawPathElements.length !== IDENTITY_TREE_DEPTH
    ) {
        throw new ZkProofError(
            `La ruta Merkle debe contener exactamente ${IDENTITY_TREE_DEPTH} elementos.`
        );
    }
    if (
        !Array.isArray(rawPathIndices) ||
        rawPathIndices.length !== IDENTITY_TREE_DEPTH
    ) {
        throw new ZkProofError(
            `La ruta Merkle debe contener exactamente ${IDENTITY_TREE_DEPTH} índices.`
        );
    }

    const pathElements = rawPathElements.map((value, index) =>
        normalizeFieldElement(value, `El elemento Merkle ${index}`, {
            allowZero: true,
        })
    );
    const pathIndices = rawPathIndices.map((value, index) => {
        const normalized = String(value);
        if (normalized !== '0' && normalized !== '1') {
            throw new ZkProofError(`El índice Merkle ${index} debe ser 0 o 1.`);
        }
        return normalized;
    });

    return {
        // The signature and witness stay in memory for local verification and
        // proving; buildZkMintPayload deliberately omits both from the relayer.
        identityRoot,
        scope,
        commitment,
        signature: signature.trim(),
        recipient: recipient.address,
        recipientSignal: recipient.signal,
        pathElements,
        pathIndices,
    };
}

export function bytesToFieldElement(bytes) {
    let value = 0n;
    for (const byte of bytes) {
        value = (value << 8n) | BigInt(byte);
    }
    const reduced = value % BN254_SCALAR_FIELD;
    return reduced === 0n ? 1n : reduced;
}

export async function hashToField(text) {
    if (typeof text !== 'string' || !text) {
        throw new ZkProofError(
            'No se puede derivar un elemento de campo de un valor vacío.'
        );
    }
    if (!globalThis.crypto?.subtle) {
        throw new ZkProofError(
            'Web Crypto no está disponible. La generación de pruebas exige HTTPS o localhost.'
        );
    }
    const digest = await globalThis.crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(text)
    );
    return bytesToFieldElement(new Uint8Array(digest));
}

export function getOrCreateSecret() {
    const storage = getLocalStorage();
    const stored = storage.getItem(SECRET_STORAGE_KEY);
    if (stored) {
        return normalizeFieldElement(stored, 'El secreto de identidad');
    }

    if (!globalThis.crypto?.getRandomValues) {
        throw new ZkProofError(
            'No hay un generador criptográfico disponible para crear el secreto de identidad.'
        );
    }
    const random = new Uint8Array(31);
    globalThis.crypto.getRandomValues(random);
    const secret = bytesToFieldElement(random).toString();
    storage.setItem(SECRET_STORAGE_KEY, secret);
    return secret;
}

export function hasSecret() {
    try {
        const secret = getLocalStorage().getItem(SECRET_STORAGE_KEY);
        if (!secret) return false;
        normalizeFieldElement(secret, 'El secreto de identidad');
        return true;
    } catch {
        return false;
    }
}

export function exportSecret() {
    const secret = getLocalStorage().getItem(SECRET_STORAGE_KEY);
    return secret
        ? normalizeFieldElement(secret, 'El secreto de identidad')
        : null;
}

export function importSecret(secret) {
    const normalized = normalizeFieldElement(secret, 'El secreto de identidad');
    getLocalStorage().setItem(SECRET_STORAGE_KEY, normalized);
    return normalized;
}

export function forgetSecret() {
    getLocalStorage().removeItem(SECRET_STORAGE_KEY);
}

async function loadPoseidon() {
    if (!poseidonPromise) {
        poseidonPromise = Promise.all([
            import('poseidon-lite/poseidon2'),
            import('poseidon-lite/poseidon3'),
        ])
            .then(([twoInputs, threeInputs]) => ({
                poseidon2: twoInputs.poseidon2,
                poseidon3: threeInputs.poseidon3,
            }))
            .catch(() => {
                poseidonPromise = undefined;
                throw new ZkProofError(
                    'No se pudo cargar Poseidon para derivar el nullifier.'
                );
            });
    }
    return poseidonPromise;
}

async function poseidonHash(inputs) {
    const { poseidon2, poseidon3 } = await loadPoseidon();
    const hasher = inputs.length === 2 ? poseidon2 : poseidon3;
    if (!hasher || ![2, 3].includes(inputs.length)) {
        throw new ZkProofError('Poseidon recibió una aridad no soportada.');
    }
    return hasher(inputs.map((value) => BigInt(value))).toString();
}

/** Derive the public nullifier committed by the circuit. */
export async function deriveNullifier(identitySecret, scope) {
    const secretSignal = normalizeFieldElement(
        identitySecret,
        'El secreto de identidad'
    );
    const scopeSignal = normalizeFieldElement(scope, 'El scope de membresía');
    return poseidonHash([secretSignal, scopeSignal]);
}

/**
 * Derive the wallet-bound commitment that the issuer must insert in its tree.
 * Only this public commitment, never the local secret, may be sent to issuer.
 */
export async function deriveIdentityCommitment({ recipient, scope }) {
    const wallet = normalizeRecipient(recipient);
    const scopeSignal = normalizeFieldElement(scope, 'El scope de membresía');
    return poseidonHash([
        getOrCreateSecret(),
        wallet.signal,
        scopeSignal,
    ]);
}

/**
 * Read the binding scope from the actual contract and, when provided, ensure
 * the wallet currently selected in the provider is still the intended one.
 */
export async function readMembershipDeployment(
    expectedChainId,
    identityRoot = null,
    expectedRecipient = null
) {
    if (!MEMBERSHIP_CONTRACT_ADDRESS) {
        throw new ZkNotProvisionedError(
            'Este despliegue no configuró el contrato de membresía.',
            ['REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS']
        );
    }
    if (!globalThis.ethereum) {
        throw new ZkProofError(
            'No hay un proveedor EVM disponible para consultar el scope de membresía.'
        );
    }

    let contractAddress;
    try {
        contractAddress = getAddress(MEMBERSHIP_CONTRACT_ADDRESS);
    } catch {
        throw new ZkNotProvisionedError(
            'La dirección configurada del contrato de membresía no es válida.',
            ['REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS']
        );
    }

    try {
        const provider = new BrowserProvider(globalThis.ethereum);
        const network = await provider.getNetwork();
        const connectedChainId = Number(network.chainId);
        if (!Number.isSafeInteger(connectedChainId) || connectedChainId <= 0) {
            throw new ZkProofError(
                'La wallet reportó un identificador de red inválido.'
            );
        }
        if (
            expectedChainId != null &&
            network.chainId !== BigInt(expectedChainId)
        ) {
            throw new ZkProofError(
                'La red conectada cambió antes de emitir la credencial identity.'
            );
        }
        if (expectedRecipient != null) {
            const expectedWallet = normalizeRecipient(expectedRecipient);
            const accounts = await provider.send('eth_accounts', []);
            if (!Array.isArray(accounts) || accounts.length === 0) {
                throw new ZkProofError(
                    'La wallet se desconectó antes de completar la prueba.'
                );
            }
            const activeWallet = normalizeRecipient(accounts[0]);
            if (activeWallet.address !== expectedWallet.address) {
                throw new ZkProofError(
                    'La cuenta activa cambió; vuelve a autorizar la credencial con la wallet seleccionada.'
                );
            }
        }
        const contract = new Contract(
            contractAddress,
            MEMBERSHIP_SCOPE_ABI,
            provider
        );
        const scope = normalizeFieldElement(
            await contract.membershipScope(),
            'El scope on-chain de membresía'
        );
        if (identityRoot != null) {
            const rootSignal = normalizeFieldElement(
                identityRoot,
                'La raíz de identidad'
            );
            if (!(await contract.isIdentityRootApproved(rootSignal))) {
                throw new ZkProofError(
                    'La raíz de la credencial identity no está aprobada por el contrato.'
                );
            }
        }
        return {
            chainId: network.chainId.toString(),
            contractAddress,
            scope,
        };
    } catch (error) {
        if (error instanceof ZkProofError) throw error;
        throw new ZkProofError(
            'No se pudo consultar membershipScope() en el contrato configurado.'
        );
    }
}

/** Canonical EIP-191 message the issuer signs after inserting commitment. */
export function buildIdentityCredentialMessage({
    recipient,
    identityRoot,
    scope,
    commitment,
}) {
    const wallet = normalizeRecipient(recipient);
    const rootSignal = normalizeFieldElement(
        identityRoot,
        'La raíz de identidad'
    );
    const scopeSignal = normalizeFieldElement(scope, 'El scope de membresía');
    const commitmentSignal = normalizeFieldElement(
        commitment,
        'El commitment de identidad'
    );
    return [
        IDENTITY_CREDENTIAL_DOMAIN,
        `recipient:${wallet.address.toLowerCase()}`,
        `identityRoot:${rootSignal}`,
        `scope:${scopeSignal}`,
        `commitment:${commitmentSignal}`,
    ].join('\n');
}

function verifyIdentityCredentialSignature(credential) {
    if (!IDENTITY_ISSUER_ADDRESS) {
        throw new ZkNotProvisionedError(
            'Este despliegue no configuró la dirección del emisor de identity.',
            ['REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS']
        );
    }

    let expectedIssuer;
    let recoveredIssuer;
    try {
        expectedIssuer = getAddress(IDENTITY_ISSUER_ADDRESS);
        recoveredIssuer = verifyMessage(
            buildIdentityCredentialMessage(credential),
            credential.signature
        );
    } catch {
        throw new ZkProofError(
            'La firma de la credencial identity no tiene un formato válido.'
        );
    }
    if (recoveredIssuer !== expectedIssuer) {
        throw new ZkProofError(
            'La credencial identity no fue firmada por el emisor configurado.'
        );
    }
}

/**
 * Verify the issuer signature and return only the protocol fields needed by
 * the prover. Any extra response fields (including accidental PII) are
 * discarded before the credential is retained by React state.
 */
export function verifyIdentityCredential(identity, recipientAddress) {
    const credential = normalizeIdentityCredential(identity, recipientAddress);
    verifyIdentityCredentialSignature(credential);
    return credential;
}

/** Drop cached Poseidon modules, mainly to isolate deterministic tests. */
export async function releaseZkResources() {
    poseidonPromise = undefined;
}

async function artifactExists(url) {
    try {
        const response = await fetch(url, { method: 'HEAD' });
        if (!response.ok) return false;
        const type = response.headers.get('content-type') || '';
        return !type.includes('text/html');
    } catch {
        return false;
    }
}

export async function checkZkAvailability() {
    const entries = Object.values(ZK_ARTIFACT_URLS);
    const results = await Promise.all(entries.map(artifactExists));
    const missing = entries.filter((_, index) => !results[index]);
    if (!IDENTITY_ISSUER_ADDRESS) {
        missing.push('REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS');
    } else {
        try {
            getAddress(IDENTITY_ISSUER_ADDRESS);
        } catch {
            missing.push('REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS');
        }
    }
    if (!MEMBERSHIP_CONTRACT_ADDRESS) {
        missing.push('REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS');
    } else {
        try {
            getAddress(MEMBERSHIP_CONTRACT_ADDRESS);
        } catch {
            missing.push('REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS');
        }
    }
    return { ready: missing.length === 0, missing };
}

// Kept as a compatibility helper for current UI consumers. The production
// contract has no legacy hash-based mint path, so ZK is no longer optional.
export function isZkMintEnabled() {
    return true;
}

async function loadSnarkjs() {
    try {
        return await import('snarkjs');
    } catch {
        throw new ZkProofError(
            'No se pudo cargar la biblioteca de pruebas (snarkjs).'
        );
    }
}

function toBytes32(value) {
    const normalized = normalizeFieldElement(value, 'El nullifier');
    return `0x${BigInt(normalized).toString(16).padStart(64, '0')}`;
}

function normalizeProofCoordinate(value, label) {
    let coordinate;
    try {
        coordinate = BigInt(value);
    } catch {
        throw new ZkProofError(`${label} no es una coordenada BN254 válida.`);
    }
    if (coordinate < 0n || coordinate >= BN254_BASE_FIELD) {
        throw new ZkProofError(`${label} está fuera del campo base BN254.`);
    }
    // Claude's relayer parses coordinates with Python int(value), so the HTTP
    // protocol uses canonical decimal strings even though snarkjs exports hex.
    return coordinate.toString();
}

function assertPublicSignals(publicSignals, expectedSignals) {
    if (!Array.isArray(publicSignals) || publicSignals.length !== 4) {
        throw new ZkProofError(
            'El prover devolvió un número inesperado de señales públicas.'
        );
    }
    const normalized = publicSignals.map((value, index) =>
        normalizeFieldElement(value, `La señal pública ${index}`)
    );
    if (normalized.some((value, index) => value !== expectedSignals[index])) {
        throw new ZkProofError(
            'La prueba no quedó ligada a la raíz, nullifier, wallet y scope esperados.'
        );
    }
    return normalized;
}

function isPair(value) {
    return Array.isArray(value) && value.length === 2;
}

async function toSolidityCalldata(
    snarkjs,
    proof,
    publicSignals,
    expectedSignals
) {
    let flat;
    try {
        const raw = await snarkjs.groth16.exportSolidityCallData(
            proof,
            publicSignals
        );
        flat = JSON.parse(`[${raw}]`);
    } catch {
        throw new ZkProofError(
            'No se pudo convertir la prueba al formato del contrato.'
        );
    }

    const [pA, pB, pC, exportedSignals] = flat;
    if (
        !isPair(pA) ||
        !isPair(pC) ||
        !isPair(pB) ||
        !pB.every(isPair)
    ) {
        throw new ZkProofError(
            'snarkjs devolvió puntos Groth16 con dimensiones inválidas.'
        );
    }
    assertPublicSignals(exportedSignals, expectedSignals);
    return {
        pA: pA.map((value, index) =>
            normalizeProofCoordinate(value, `pA[${index}]`)
        ),
        pB: pB.map((row, rowIndex) =>
            row.map((value, columnIndex) =>
                normalizeProofCoordinate(
                    value,
                    `pB[${rowIndex}][${columnIndex}]`
                )
            )
        ),
        pC: pC.map((value, index) =>
            normalizeProofCoordinate(value, `pC[${index}]`)
        ),
    };
}

/**
 * Generate a wallet-bound proof locally.
 *
 * `identity.signature` is required as issuer provenance, but it never enters
 * the witness or returned payload. Eligibility comes from Merkle inclusion in
 * an identity root approved by the contract.
 */
export async function generateIdentityProof({
    identity,
    recipient,
    expectedScope,
}) {
    const credential = verifyIdentityCredential(identity, recipient);
    if (
        expectedScope != null &&
        credential.scope !==
            normalizeFieldElement(expectedScope, 'El scope on-chain de membresía')
    ) {
        throw new ZkProofError(
            'La credencial identity pertenece a otro contrato o red.'
        );
    }
    const availability = await checkZkAvailability();
    if (!availability.ready) {
        throw new ZkNotProvisionedError(
            'Este despliegue no publicó los artefactos exactos del circuito ZK.',
            availability.missing
        );
    }

    const identitySecret = getOrCreateSecret();
    const localCommitment = await poseidonHash([
        identitySecret,
        credential.recipientSignal,
        credential.scope,
    ]);
    if (localCommitment !== credential.commitment) {
        throw new ZkProofError(
            'La credencial identity no corresponde al secreto local y la wallet receptora.'
        );
    }
    const nullifierSignal = await deriveNullifier(
        identitySecret,
        credential.scope
    );
    const expectedSignals = [
        credential.identityRoot,
        nullifierSignal,
        credential.recipientSignal,
        credential.scope,
    ];
    const input = {
        identitySecret,
        pathElements: credential.pathElements,
        pathIndices: credential.pathIndices,
        identityRoot: credential.identityRoot,
        nullifierHash: nullifierSignal,
        recipient: credential.recipientSignal,
        scope: credential.scope,
    };

    const snarkjs = await loadSnarkjs();
    let proof;
    let publicSignals;
    try {
        ({ proof, publicSignals } = await snarkjs.groth16.fullProve(
            input,
            ZK_ARTIFACT_URLS.wasm,
            ZK_ARTIFACT_URLS.zkey
        ));
    } catch (error) {
        console.error('ZK proof generation failed:', error);
        throw new ZkProofError(
            'No se pudo generar la prueba. La credencial puede no corresponder a esta wallet, secreto o circuito.'
        );
    }

    const normalizedSignals = assertPublicSignals(
        publicSignals,
        expectedSignals
    );
    const { pA, pB, pC } = await toSolidityCalldata(
        snarkjs,
        proof,
        normalizedSignals,
        expectedSignals
    );

    return {
        proof,
        publicSignals: normalizedSignals,
        pA,
        pB,
        pC,
        nullifierHash: toBytes32(nullifierSignal),
        identityRoot: credential.identityRoot,
        recipient: credential.recipient,
        scope: credential.scope,
    };
}

export async function verifyProofLocally(proof, publicSignals) {
    let verificationKey;
    try {
        const response = await fetch(ZK_ARTIFACT_URLS.verificationKey);
        if (!response.ok) return null;
        const type = response.headers.get('content-type') || '';
        if (type.includes('text/html')) return null;
        verificationKey = await response.json();
    } catch {
        return null;
    }

    try {
        const snarkjs = await loadSnarkjs();
        return await snarkjs.groth16.verify(
            verificationKey,
            publicSignals,
            proof
        );
    } catch (error) {
        console.error('Local proof verification failed:', error);
        return false;
    }
}
