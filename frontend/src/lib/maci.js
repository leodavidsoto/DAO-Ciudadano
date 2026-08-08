/**
 * Browser MACI ballot encryption.
 *
 * Keys are opaque in-memory objects. This module never serializes the voter
 * private key, command, EdDSA signature, salt or ECDH shared key.
 */
import {
    inCurve,
    mulPointEscalar,
    r as BABY_JUB_FIELD_MODULUS,
    subOrder,
} from './babyJubjub';
import { BrowserProvider, Contract, ZeroAddress, getAddress } from 'ethers';
import { poseidon2, poseidon3, poseidon6 } from 'poseidon-lite';

export const MACI_PROTOCOL_VERSION = 'maci-v2.5.0';
const IDENTITY_POINT = [0n, 1n];
const UINT50_LIMIT = 1n << 50n;
const MACI_COORDINATOR_ABI = [
    'function coordinatorPubKeyX() view returns (uint256)',
    'function coordinatorPubKeyY() view returns (uint256)',
    'function tallyVerifier() view returns (address)',
];

export class MaciBallotError extends Error {
    constructor(message, code = 'MACI_BALLOT_ERROR') {
        super(message);
        this.name = 'MaciBallotError';
        this.code = code;
    }
}

const pointsEqual = (left, right) =>
    left[0] === right[0] && left[1] === right[1];

const toCanonicalCoordinate = (value, label) => {
    if (
        (typeof value !== 'string' && typeof value !== 'bigint') ||
        (typeof value === 'string' && !/^(?:0|[1-9][0-9]*)$/.test(value))
    ) {
        throw new MaciBallotError(`${label} no es una coordenada decimal canónica.`);
    }
    let parsed;
    try {
        parsed = BigInt(value);
    } catch {
        throw new MaciBallotError(`${label} no es una coordenada válida.`);
    }
    if (parsed < 0n || parsed >= BABY_JUB_FIELD_MODULUS) {
        throw new MaciBallotError(`${label} está fuera del campo Baby Jubjub.`);
    }
    return parsed;
};

export const normalizeMaciPublicKey = (publicKey, label = 'La llave MACI') => {
    if (!publicKey || typeof publicKey !== 'object') {
        throw new MaciBallotError(`${label} no está disponible.`);
    }
    const point = [
        toCanonicalCoordinate(publicKey.x, `${label}.x`),
        toCanonicalCoordinate(publicKey.y, `${label}.y`),
    ];
    if (!inCurve(point) || pointsEqual(point, IDENTITY_POINT)) {
        throw new MaciBallotError(`${label} no es un punto Baby Jubjub válido.`);
    }
    // On-curve is insufficient: reject low-order points before ECDH.
    if (!pointsEqual(mulPointEscalar(point, subOrder), IDENTITY_POINT)) {
        throw new MaciBallotError(`${label} no pertenece al subgrupo primo.`);
    }
    return point;
};

const publicKeyHashFromPoint = (point) =>
    `0x${poseidon2(point).toString(16).padStart(64, '0')}`;

export const deriveMaciPublicKeyHash = (publicKey) =>
    publicKeyHashFromPoint(normalizeMaciPublicKey(publicKey));

const normalizeUint50 = (value, label, { positive = false } = {}) => {
    if (
        (typeof value !== 'string' && typeof value !== 'bigint' && typeof value !== 'number') ||
        (typeof value === 'number' && !Number.isSafeInteger(value)) ||
        (typeof value === 'string' && !/^(?:0|[1-9][0-9]*)$/.test(value))
    ) {
        throw new MaciBallotError(`${label} no es un entero MACI canónico.`);
    }
    let parsed;
    try {
        parsed = BigInt(value);
    } catch {
        throw new MaciBallotError(`${label} no es un entero MACI válido.`);
    }
    if (parsed < 0n || parsed >= UINT50_LIMIT || (positive && parsed === 0n)) {
        throw new MaciBallotError(`${label} está fuera del rango MACI de 50 bits.`);
    }
    return parsed;
};

const readEnvelope = (response) => response?.data ?? response;

const normalizeEvmAddress = (value, label) => {
    if (typeof value !== 'string' || !value.trim()) {
        throw new MaciBallotError(`${label} no está configurado.`);
    }
    try {
        const address = getAddress(value);
        if (address === ZeroAddress) throw new Error('zero address');
        return address;
    } catch {
        throw new MaciBallotError(`${label} no es una dirección EVM válida.`);
    }
};

export const getMaciReadiness = (response) => {
    const status = readEnvelope(response) || {};
    const missing = [];
    if (status.key_registry !== true) missing.push('registro de llaves');
    if (status.private_voting !== true) missing.push('votación privada');
    if (status.coordinator_configured !== true) missing.push('coordinador MACI');
    if (status.tally_proof !== true) missing.push('verificación del tally');
    if (status.poll_bound_messages !== true) missing.push('vinculación mensaje-poll');
    if (status.stateful_nonces !== true) missing.push('nonce ligado al estado');
    if (status.unique_tally_leaves !== true) missing.push('unicidad de hojas del tally');
    if (status.process_tally_linked !== true) missing.push('encadenamiento de pruebas');
    return {
        ready: missing.length === 0,
        missing,
        detail: typeof status.detail === 'string' ? status.detail : '',
    };
};

const normalizeVoteOptions = (options) => {
    const required = ['for', 'against', 'abstain'];
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
        throw new MaciBallotError('El poll no publicó el mapeo de opciones de voto.');
    }
    const normalized = {};
    const seen = new Set();
    for (const choice of required) {
        const index = normalizeUint50(options[choice], `vote_options.${choice}`);
        const key = index.toString();
        if (seen.has(key)) {
            throw new MaciBallotError('El poll reutiliza un índice para opciones distintas.');
        }
        seen.add(key);
        normalized[choice] = index;
    }
    return normalized;
};

export const normalizeMaciVotingConfig = (
    response,
    { proposalId, chainId, now = Date.now() }
) => {
    const envelope = readEnvelope(response);
    const config = envelope?.config ?? envelope?.poll ?? envelope;
    if (!config || config.protocol_version !== MACI_PROTOCOL_VERSION) {
        throw new MaciBallotError('El backend no publicó un poll MACI 2.5 compatible.');
    }
    if (String(config.proposal_id) !== String(proposalId)) {
        throw new MaciBallotError('El poll MACI no corresponde a la propuesta elegida.');
    }
    const configuredChainId = Number(config.chain_id);
    if (!Number.isSafeInteger(configuredChainId) || configuredChainId <= 0) {
        throw new MaciBallotError('El poll MACI publicó una red inválida.');
    }
    if (chainId != null && Number(chainId) !== configuredChainId) {
        throw new MaciBallotError('El poll MACI y la wallet están en redes distintas.');
    }
    if (config.accepting_messages !== true) {
        throw new MaciBallotError('El poll ya no acepta mensajes cifrados.');
    }
    const deadline = Date.parse(config.deadline);
    if (!Number.isFinite(deadline) || deadline <= now) {
        throw new MaciBallotError('El plazo del poll MACI ya terminó.');
    }
    if (!/^0x[0-9a-fA-F]{64}$/.test(config.coordinator_key_hash || '')) {
        throw new MaciBallotError('El poll no ancló la llave pública del coordinador.');
    }
    const coordinatorContract = normalizeEvmAddress(
        config.coordinator_contract,
        'El contrato coordinador MACI'
    );

    const coordinatorPoint = normalizeMaciPublicKey(
        config.coordinator_public_key,
        'La llave del coordinador'
    );
    if (
        publicKeyHashFromPoint(coordinatorPoint).toLowerCase() !==
        config.coordinator_key_hash.toLowerCase()
    ) {
        throw new MaciBallotError('La llave del coordinador no coincide con su anclaje Poseidon.');
    }
    const voteWeight = normalizeUint50(config.vote_weight, 'vote_weight', {
        positive: true,
    });
    if (voteWeight !== 1n) {
        throw new MaciBallotError('Esta urna admite solamente una preferencia por ciudadano.');
    }

    return {
        protocolVersion: MACI_PROTOCOL_VERSION,
        proposalId: String(proposalId),
        pollId: normalizeUint50(config.poll_id, 'poll_id'),
        stateIndex: normalizeUint50(config.state_index, 'state_index', { positive: true }),
        nonce: normalizeUint50(config.nonce, 'nonce', { positive: true }),
        voteWeight,
        voteOptions: normalizeVoteOptions(config.vote_options),
        coordinatorPoint,
        coordinatorKeyHash: config.coordinator_key_hash,
        coordinatorContract,
        deadline,
        chainId: configuredChainId,
    };
};

/**
 * Bind the encryption key to the coordinator deployed in the trusted frontend
 * manifest. A backend-provided point and hash are not an anchor by themselves:
 * a compromised API could replace both. The wallet RPC is used only for
 * read-only chain verification and never receives the ballot plaintext.
 */
export const verifyMaciCoordinatorOnChain = async ({
    config,
    ethereum,
    expectedAddress = process.env.REACT_APP_MACI_COORDINATOR_ADDRESS,
    expectedTallyVerifier = process.env.REACT_APP_MACI_TALLY_VERIFIER_ADDRESS,
}) => {
    if (!config || !Array.isArray(config.coordinatorPoint)) {
        throw new MaciBallotError('La configuración MACI no está normalizada.');
    }
    const trustedAddress = normalizeEvmAddress(
        expectedAddress,
        'REACT_APP_MACI_COORDINATOR_ADDRESS'
    );
    if (trustedAddress !== config.coordinatorContract) {
        throw new MaciBallotError(
            'El coordinador MACI del backend no coincide con el despliegue confiable.'
        );
    }
    if (!ethereum || typeof ethereum.request !== 'function') {
        throw new MaciBallotError('La wallet no permite verificar el coordinador on-chain.');
    }
    const trustedTallyVerifier = normalizeEvmAddress(
        expectedTallyVerifier,
        'REACT_APP_MACI_TALLY_VERIFIER_ADDRESS'
    );

    try {
        const provider = new BrowserProvider(ethereum, 'any');
        const initialNetwork = await provider.getNetwork();
        if (Number(initialNetwork.chainId) !== config.chainId) {
            throw new MaciBallotError(
                'La wallet cambió de red antes de verificar el coordinador MACI.'
            );
        }
        if (await provider.getCode(trustedAddress) === '0x') {
            throw new MaciBallotError('El coordinador MACI no tiene código desplegado.');
        }

        const coordinator = new Contract(
            trustedAddress,
            MACI_COORDINATOR_ABI,
            provider
        );
        const [onChainX, onChainY, rawTallyVerifier] = await Promise.all([
            coordinator.coordinatorPubKeyX(),
            coordinator.coordinatorPubKeyY(),
            coordinator.tallyVerifier(),
        ]);
        const onChainPoint = normalizeMaciPublicKey(
            { x: onChainX.toString(), y: onChainY.toString() },
            'La llave coordinadora on-chain'
        );
        if (!pointsEqual(onChainPoint, config.coordinatorPoint)) {
            throw new MaciBallotError(
                'La llave coordinadora del poll no coincide con el contrato on-chain.'
            );
        }

        const tallyVerifier = normalizeEvmAddress(
            rawTallyVerifier,
            'El verificador de tally MACI'
        );
        if (tallyVerifier !== trustedTallyVerifier) {
            throw new MaciBallotError(
                'El verificador de tally no coincide con el despliegue confiable.'
            );
        }
        if (await provider.getCode(tallyVerifier) === '0x') {
            throw new MaciBallotError('El verificador de tally MACI no está desplegado.');
        }
        const finalNetwork = await provider.getNetwork();
        if (finalNetwork.chainId !== initialNetwork.chainId) {
            throw new MaciBallotError(
                'La wallet cambió de red durante la verificación del coordinador MACI.'
            );
        }
        return { coordinatorContract: trustedAddress, tallyVerifier };
    } catch (error) {
        if (error instanceof MaciBallotError) throw error;
        throw new MaciBallotError(
            'No fue posible verificar el coordinador y el tally MACI on-chain.'
        );
    }
};

const keypairHasSafePublicKey = (keypair) => {
    const raw = keypair?.pubKey?.rawPubKey;
    if (!Array.isArray(raw) || raw.length !== 2) return false;
    try {
        normalizeMaciPublicKey({ x: raw[0].toString(), y: raw[1].toString() });
        return Boolean(keypair?.privKey);
    } catch {
        return false;
    }
};

export const createMaciKeypair = async () => {
    const { Keypair } = await import('maci-domainobjs');
    // A zero/low-order result is fantastically unlikely, but cryptographic
    // APIs should still validate their output rather than assume it.
    for (let attempt = 0; attempt < 8; attempt += 1) {
        const keypair = new Keypair();
        if (keypairHasSafePublicKey(keypair)) return keypair;
    }
    throw new MaciBallotError('No fue posible generar una llave MACI segura.');
};

export const getMaciPublicKey = (keypair) => {
    if (!keypairHasSafePublicKey(keypair)) {
        throw new MaciBallotError('La llave de votante MACI no es válida.');
    }
    const value = keypair.pubKey.asContractParam();
    return { x: value.x, y: value.y };
};

export const encryptMaciBallot = async ({ voterKeypair, config, choice }) => {
    if (!keypairHasSafePublicKey(voterKeypair)) {
        throw new MaciBallotError('No existe una llave privada de votación válida en memoria.');
    }
    if (
        !config?.voteOptions ||
        !Object.prototype.hasOwnProperty.call(config.voteOptions, choice)
    ) {
        throw new MaciBallotError('Selecciona una opción de voto válida.');
    }
    const [{ Keypair, PubKey }, { signMessage, verifySignature }] = await Promise.all([
        import('maci-domainobjs'),
        import('@zk-kit/eddsa-poseidon'),
    ]);
    const coordinator = new PubKey(config.coordinatorPoint);
    const voterPublicKey = voterKeypair.pubKey.rawPubKey.map(BigInt);
    const command = [
        config.stateIndex,
        config.voteOptions[choice],
        config.voteWeight,
        config.nonce,
        voterPublicKey[0],
        voterPublicKey[1],
    ];
    const commandHash = poseidon6(command);
    const signature = signMessage(
        voterKeypair.privKey.rawPrivKey.toString(),
        commandHash
    );
    if (!verifySignature(commandHash, signature, voterPublicKey)) {
        throw new MaciBallotError('La firma interna de la papeleta MACI falló.');
    }

    const ephemeralKeypair = await createMaciKeypair();
    const sharedKey = Keypair.genEcdhSharedKey(
        ephemeralKeypair.privKey,
        coordinator
    );
    normalizeMaciPublicKey(
        { x: sharedKey[0].toString(), y: sharedKey[1].toString() },
        'La llave ECDH compartida'
    );

    // This repository's approved processMessages.circom boundary deliberately
    // differs from reference MACI's packed PCommand + poseidonEncrypt format.
    // Keep these ten fields and this additive stream cipher in lockstep with
    // circuits/processMessages.circom. Using PCommand.encrypt here produces a
    // valid reference-MACI message which this project's circuit cannot tally.
    const plaintext = [
        ...command,
        BigInt(signature.R8[0]),
        BigInt(signature.R8[1]),
        BigInt(signature.S),
        0n,
    ];
    const ciphertext = plaintext.map((value, index) => {
        const pad = poseidon3([sharedKey[0], sharedKey[1], BigInt(index)]);
        return (value + pad) % BABY_JUB_FIELD_MODULUS;
    });

    return {
        protocolVersion: config.protocolVersion,
        proposalId: config.proposalId,
        pollId: config.pollId.toString(),
        message: { data: ciphertext.map(String) },
        encryptionPublicKey: getMaciPublicKey(ephemeralKeypair),
        coordinatorKeyHash: config.coordinatorKeyHash,
    };
};

export const createBallotIdempotencyKey = () => {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    if (!globalThis.crypto?.getRandomValues) {
        throw new MaciBallotError('No hay entropía segura para identificar la papeleta.');
    }
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
};
