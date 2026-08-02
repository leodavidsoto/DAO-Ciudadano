/**
 * ERC-4337 transport for the ZK membership mint.
 *
 * The browser owns the Safe signature. Pimlico credentials and sponsorship
 * policy stay behind the authenticated backend. The backend may estimate and
 * sponsor the operation, but it cannot replace the Safe call or its owner.
 */
import { toSafeSmartAccount } from 'permissionless/accounts';
import { toOwner } from 'permissionless/utils';
import {
    createPublicClient,
    custom,
    defineChain,
    encodeFunctionData,
    getAddress,
    isHex,
    size as getHexSize,
    toHex,
} from 'viem';
import {
    entryPoint07Address,
    getUserOperationHash,
} from 'viem/account-abstraction';

export const SAFE_VERSION = '1.4.1';
export const SAFE_SALT_NONCE = 0n;
export const SAFE_NONCE_KEY = 0n;
export const ENTRY_POINT_VERSION = '0.7';
export const CANONICAL_ENTRY_POINT_V07 = getAddress(entryPoint07Address);
export const CANONICAL_SAFE_4337_MODULE_V141_V07 = getAddress(
    '0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226'
);

const UINT256_MAX = (1n << 256n) - 1n;
const BN254_BASE_FIELD =
    21888242871839275222246405745257275088696311157297823662689037894645226208583n;
const SNARK_SCALAR_FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;
const MAX_GAS_FIELD = 5_000_000n;
const MAX_PRE_VERIFICATION_GAS = 2_000_000n;
const MAX_FEE_PER_GAS = 1_000_000_000_000n;

const USER_OPERATION_KEYS = new Set([
    'sender',
    'nonce',
    'factory',
    'factoryData',
    'callData',
    'callGasLimit',
    'verificationGasLimit',
    'preVerificationGas',
    'maxFeePerGas',
    'maxPriorityFeePerGas',
    'paymaster',
    'paymasterData',
    'paymasterVerificationGasLimit',
    'paymasterPostOpGasLimit',
    'signature',
]);

const REQUIRED_SPONSORED_FIELDS = [
    'sender',
    'nonce',
    'callData',
    'callGasLimit',
    'verificationGasLimit',
    'preVerificationGas',
    'maxFeePerGas',
    'maxPriorityFeePerGas',
    'paymaster',
    'paymasterData',
    'paymasterVerificationGasLimit',
    'paymasterPostOpGasLimit',
    'signature',
];

const MEMBERSHIP_MINT_ABI = [{
    type: 'function',
    name: 'mintMembership',
    stateMutability: 'nonpayable',
    inputs: [
        { name: 'to', type: 'address' },
        { name: 'pA', type: 'uint256[2]' },
        { name: 'pB', type: 'uint256[2][2]' },
        { name: 'pC', type: 'uint256[2]' },
        { name: 'nullifierHash', type: 'bytes32' },
        { name: 'identityRoot', type: 'uint256' },
    ],
    outputs: [{ name: 'tokenId', type: 'uint256' }],
}];

export class AccountAbstractionError extends Error {
    constructor(message, code = 'AA_CLIENT_ERROR') {
        super(message);
        this.name = 'AccountAbstractionError';
        this.code = code;
    }
}

const readResponseData = (response) => response?.data ?? response;

const toStrictBigInt = (value, label, { max = UINT256_MAX, positive = false } = {}) => {
    if (
        typeof value !== 'bigint' &&
        typeof value !== 'string'
    ) {
        throw new AccountAbstractionError(`${label} no tiene un formato entero seguro.`);
    }
    if (typeof value === 'string' && !/^(?:0x[0-9a-fA-F]+|[0-9]+)$/.test(value)) {
        throw new AccountAbstractionError(`${label} no tiene un formato entero canónico.`);
    }
    let parsed;
    try {
        parsed = BigInt(value);
    } catch {
        throw new AccountAbstractionError(`${label} no es un entero válido.`);
    }
    if (parsed < 0n || parsed > max || (positive && parsed === 0n)) {
        throw new AccountAbstractionError(`${label} está fuera de rango.`);
    }
    return parsed;
};

const normalizeProofPoint = (value, label, shape) => {
    if (shape === 'g1') {
        if (!Array.isArray(value) || value.length !== 2) {
            throw new AccountAbstractionError(`${label} debe tener dos coordenadas.`);
        }
        return value.map((coordinate, index) =>
            toStrictBigInt(coordinate, `${label}[${index}]`, {
                max: BN254_BASE_FIELD - 1n,
            })
        );
    }
    if (!Array.isArray(value) || value.length !== 2) {
        throw new AccountAbstractionError(`${label} debe ser una matriz 2x2.`);
    }
    return value.map((row, rowIndex) =>
        normalizeProofPoint(row, `${label}[${rowIndex}]`, 'g1')
    );
};

const normalizeAddress = (value, label) => {
    try {
        return getAddress(value);
    } catch {
        throw new AccountAbstractionError(`${label} no es una dirección EVM válida.`);
    }
};

const normalizeHex = (value, label, expectedSize) => {
    if (
        !isHex(value, { strict: true }) ||
        (value.length - 2) % 2 !== 0 ||
        (expectedSize != null && getHexSize(value) !== expectedSize)
    ) {
        throw new AccountAbstractionError(`${label} no es hexadecimal válido.`);
    }
    return value;
};

const normalizeHash = (value, label) =>
    normalizeHex(value, label, 32).toLowerCase();

/** Build the one and only call the Safe is allowed to execute. */
export const buildSafeMintCall = ({
    membershipContract,
    walletAddress,
    pA,
    pB,
    pC,
    nullifierHash,
    identityRoot,
}) => {
    const recipient = normalizeAddress(walletAddress, 'La wallet receptora');
    const target = normalizeAddress(membershipContract, 'El contrato de membresía');
    const normalizedPA = normalizeProofPoint(pA, 'pA', 'g1');
    const normalizedPB = normalizeProofPoint(pB, 'pB', 'g2');
    const normalizedPC = normalizeProofPoint(pC, 'pC', 'g1');
    const normalizedNullifier = normalizeHex(nullifierHash, 'El nullifier', 32);
    const normalizedRoot = toStrictBigInt(identityRoot, 'La raíz de identidad', {
        max: SNARK_SCALAR_FIELD - 1n,
    });

    return {
        to: target,
        value: 0n,
        data: encodeFunctionData({
            abi: MEMBERSHIP_MINT_ABI,
            functionName: 'mintMembership',
            args: [
                recipient,
                normalizedPA,
                normalizedPB,
                normalizedPC,
                normalizedNullifier,
                normalizedRoot,
            ],
        }),
    };
};

const normalizeMintProof = (proof) => {
    const chainId = Number(proof?.chainId);
    if (!Number.isSafeInteger(chainId) || chainId <= 0) {
        throw new AccountAbstractionError('La prueba ZK no identifica una red válida.');
    }
    return {
        walletAddress: normalizeAddress(proof.walletAddress, 'La wallet receptora'),
        membershipContract: normalizeAddress(
            proof.membershipContract,
            'El contrato de membresía'
        ),
        chainId,
        pA: normalizeProofPoint(proof.pA, 'pA', 'g1').map(String),
        pB: normalizeProofPoint(proof.pB, 'pB', 'g2')
            .map((row) => row.map(String)),
        pC: normalizeProofPoint(proof.pC, 'pC', 'g1').map(String),
        nullifierHash: normalizeHex(proof.nullifierHash, 'El nullifier', 32),
        identityRoot: toStrictBigInt(proof.identityRoot, 'La raíz de identidad', {
            max: SNARK_SCALAR_FIELD - 1n,
        }).toString(),
    };
};

export const normalizeAccountAbstractionConfig = (response) => {
    const envelope = readResponseData(response);
    const config = envelope?.config ?? envelope;
    if (!config || config.enabled !== true || config.sponsorship_enabled !== true) {
        throw new AccountAbstractionError(
            'El backend todavía no habilitó el minteo subsidiado ERC-4337.',
            'AA_NOT_CONFIGURED'
        );
    }
    if (config.account_type !== 'safe' || config.safe_version !== SAFE_VERSION) {
        throw new AccountAbstractionError('La configuración de Smart Account no es compatible.');
    }
    if (config.entry_point_version !== ENTRY_POINT_VERSION) {
        throw new AccountAbstractionError('El backend no está usando EntryPoint v0.7.');
    }
    if (config.bundler_provider !== 'pimlico' || config.paymaster_provider !== 'pimlico') {
        throw new AccountAbstractionError('El patrocinio no usa el perfil Pimlico aprobado.');
    }

    const chainId = Number(config.chain_id);
    if (!Number.isSafeInteger(chainId) || chainId <= 0) {
        throw new AccountAbstractionError('El backend publicó una red ERC-4337 inválida.');
    }
    const entryPoint = normalizeAddress(config.entry_point, 'El EntryPoint');
    if (entryPoint !== CANONICAL_ENTRY_POINT_V07) {
        throw new AccountAbstractionError('El EntryPoint publicado no es el canónico v0.7.');
    }
    if (toStrictBigInt(config.safe_salt_nonce, 'El saltNonce de Safe') !== SAFE_SALT_NONCE) {
        throw new AccountAbstractionError('El saltNonce de Safe no coincide con el perfil aprobado.');
    }
    if (config.use_multi_send_for_setup !== false) {
        throw new AccountAbstractionError('La derivación contrafactual de Safe es ambigua.');
    }
    const safe4337ModuleAddress = normalizeAddress(
        config.safe_4337_module_address,
        'El módulo Safe4337'
    );
    if (safe4337ModuleAddress !== CANONICAL_SAFE_4337_MODULE_V141_V07) {
        throw new AccountAbstractionError(
            'El módulo Safe4337 no coincide con Safe 1.4.1 y EntryPoint v0.7.'
        );
    }
    const paymaster = normalizeAddress(config.paymaster, 'El paymaster Pimlico');

    return {
        chainId,
        chainName: typeof config.chain_name === 'string' ? config.chain_name : `Chain ${chainId}`,
        entryPoint,
        safe4337ModuleAddress,
        paymaster,
    };
};

const chainForProvider = ({ chainId, chainName }) => defineChain({
    id: chainId,
    name: chainName,
    nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    rpcUrls: { default: { http: [] } },
});

const verifyActiveProvider = async (provider, expectedOwner, expectedChainId) => {
    if (!provider || typeof provider.request !== 'function') {
        throw new AccountAbstractionError(
            'No hay una wallet EIP-1193 disponible para firmar la operación.',
            'WALLET_UNAVAILABLE'
        );
    }
    if (provider.isMetaMask !== true) {
        throw new AccountAbstractionError(
            'La operación requiere la instancia MetaMask conectada por SIWE.',
            'METAMASK_PROVIDER_REQUIRED'
        );
    }
    const [accounts, chainHex] = await Promise.all([
        provider.request({ method: 'eth_accounts' }),
        provider.request({ method: 'eth_chainId' }),
    ]);
    if (!Array.isArray(accounts) || accounts.length === 0) {
        throw new AccountAbstractionError('La wallet se desconectó antes de firmar.');
    }
    const activeOwner = normalizeAddress(accounts[0], 'La cuenta activa');
    if (activeOwner !== normalizeAddress(expectedOwner, 'La wallet propietaria')) {
        throw new AccountAbstractionError(
            'La cuenta activa cambió; vuelve a autorizar el minteo con esa wallet.'
        );
    }
    const activeChainId = Number(BigInt(chainHex));
    if (activeChainId !== expectedChainId) {
        throw new AccountAbstractionError('La red activa cambió antes de construir la operación.');
    }
};

/** Derive the citizen Safe and its unsigned/stub-signed v0.7 operation. */
export const buildSafeUserOperationDraft = async ({
    provider,
    ownerAddress,
    config,
    call,
}) => {
    await verifyActiveProvider(provider, ownerAddress, config.chainId);
    const pinnedOwnerAddress = normalizeAddress(ownerAddress, 'La wallet propietaria');
    const owner = await toOwner({
        owner: provider,
        address: pinnedOwnerAddress,
    });
    if (normalizeAddress(owner.address, 'El owner de Safe') !== pinnedOwnerAddress) {
        throw new AccountAbstractionError('Safe resolvió un owner distinto a la wallet activa.');
    }
    const client = createPublicClient({
        chain: chainForProvider(config),
        transport: custom(provider),
    });
    const safeAccount = await toSafeSmartAccount({
        client,
        owners: [owner],
        threshold: 1n,
        version: SAFE_VERSION,
        entryPoint: { address: config.entryPoint, version: ENTRY_POINT_VERSION },
        safe4337ModuleAddress: config.safe4337ModuleAddress,
        saltNonce: SAFE_SALT_NONCE,
        nonceKey: SAFE_NONCE_KEY,
        useMultiSendForSetup: false,
    });
    const callData = await safeAccount.encodeCalls([call]);
    const [{ factory, factoryData }, nonce, signature] = await Promise.all([
        safeAccount.getFactoryArgs(),
        safeAccount.getNonce({ key: SAFE_NONCE_KEY }),
        safeAccount.getStubSignature(),
    ]);
    if (Boolean(factory) !== Boolean(factoryData)) {
        throw new AccountAbstractionError('Safe devolvió datos incompletos de despliegue.');
    }

    return {
        safeAccount,
        draft: {
            sender: safeAccount.address,
            nonce,
            ...(factory ? { factory, factoryData } : {}),
            callData,
            signature,
        },
    };
};

const numericUserOperationFields = new Set([
    'nonce',
    'callGasLimit',
    'verificationGasLimit',
    'preVerificationGas',
    'maxFeePerGas',
    'maxPriorityFeePerGas',
    'paymasterVerificationGasLimit',
    'paymasterPostOpGasLimit',
]);
const addressUserOperationFields = new Set(['sender', 'factory', 'paymaster']);
const hexUserOperationFields = new Set([
    'factoryData',
    'callData',
    'paymasterData',
    'signature',
]);

export const deserializeUserOperation = (rawOperation) => {
    if (!rawOperation || typeof rawOperation !== 'object' || Array.isArray(rawOperation)) {
        throw new AccountAbstractionError('El backend no devolvió una UserOperation válida.');
    }
    for (const key of Object.keys(rawOperation)) {
        if (!USER_OPERATION_KEYS.has(key)) {
            throw new AccountAbstractionError(`La UserOperation contiene el campo no permitido ${key}.`);
        }
    }
    for (const key of REQUIRED_SPONSORED_FIELDS) {
        if (rawOperation[key] == null) {
            throw new AccountAbstractionError(`La UserOperation patrocinada no incluye ${key}.`);
        }
    }

    const operation = {};
    for (const [key, value] of Object.entries(rawOperation)) {
        if (value == null) continue;
        if (numericUserOperationFields.has(key)) {
            operation[key] = toStrictBigInt(value, key);
        } else if (addressUserOperationFields.has(key)) {
            operation[key] = normalizeAddress(value, key);
        } else if (hexUserOperationFields.has(key)) {
            operation[key] = normalizeHex(value, key);
        }
    }

    if (Boolean(operation.factory) !== Boolean(operation.factoryData)) {
        throw new AccountAbstractionError('La fábrica contrafactual está incompleta.');
    }
    if (operation.callGasLimit > MAX_GAS_FIELD || operation.verificationGasLimit > MAX_GAS_FIELD) {
        throw new AccountAbstractionError('Los límites de gas patrocinados exceden la política local.');
    }
    if (
        operation.paymasterVerificationGasLimit > MAX_GAS_FIELD ||
        operation.paymasterPostOpGasLimit > MAX_GAS_FIELD ||
        operation.preVerificationGas > MAX_PRE_VERIFICATION_GAS
    ) {
        throw new AccountAbstractionError('El presupuesto de paymaster excede la política local.');
    }
    if (
        operation.maxFeePerGas > MAX_FEE_PER_GAS ||
        operation.maxPriorityFeePerGas > operation.maxFeePerGas
    ) {
        throw new AccountAbstractionError('Las tarifas patrocinadas exceden la política local.');
    }
    return operation;
};

export const serializeUserOperation = (operation) => {
    const result = {};
    for (const [key, value] of Object.entries(operation)) {
        if (value == null || !USER_OPERATION_KEYS.has(key)) continue;
        result[key] = typeof value === 'bigint' ? toHex(value) : value;
    }
    return result;
};

const sameAddress = (left, right) =>
    normalizeAddress(left, 'sender') === normalizeAddress(right, 'sender');

const assertPreparedOperationMatchesDraft = (prepared, draft, config) => {
    if (!sameAddress(prepared.sender, draft.sender)) {
        throw new AccountAbstractionError('El backend intentó cambiar la Safe emisora.');
    }
    if (prepared.nonce !== draft.nonce || prepared.callData !== draft.callData) {
        throw new AccountAbstractionError('El backend alteró la llamada o nonce de la Safe.');
    }
    const preparedFactory = prepared.factory ?? null;
    const draftFactory = draft.factory ?? null;
    const preparedFactoryData = prepared.factoryData ?? null;
    const draftFactoryData = draft.factoryData ?? null;
    if (Boolean(preparedFactory) !== Boolean(draftFactory) ||
        (preparedFactory && !sameAddress(preparedFactory, draftFactory)) ||
        preparedFactoryData !== draftFactoryData) {
        throw new AccountAbstractionError('El backend alteró el despliegue contrafactual de Safe.');
    }
    if (!sameAddress(prepared.paymaster, config.paymaster)) {
        throw new AccountAbstractionError('El backend sustituyó el paymaster aprobado.');
    }
};

const assertExpectedUserOperationHash = (reportedHash, expectedHash) => {
    const normalizedHash = normalizeHash(
        reportedHash,
        'El hash de UserOperation devuelto por el bundler'
    );
    if (normalizedHash !== expectedHash) {
        throw new AccountAbstractionError(
            'El backend devolvió el hash de una UserOperation distinta a la firmada.'
        );
    }
    return normalizedHash;
};

const assertPositiveTokenId = (value) => {
    if (typeof value === 'number') {
        if (!Number.isSafeInteger(value) || value <= 0) {
            throw new AccountAbstractionError('El tokenId confirmado no es válido.');
        }
        return;
    }
    toStrictBigInt(value, 'El tokenId confirmado', { positive: true });
};

const readConfirmedMint = (data) => {
    const hasTransactionHash = data?.tx_hash != null;
    const hasTokenId = data?.token_id != null;
    if (hasTransactionHash !== hasTokenId) {
        throw new AccountAbstractionError(
            'La confirmación on-chain está incompleta: faltan tx_hash o token_id.'
        );
    }
    if (!hasTransactionHash) return null;

    const txHash = normalizeHash(data.tx_hash, 'El hash de transacción confirmado');
    assertPositiveTokenId(data.token_id);
    return { ...data, tx_hash: txHash };
};

const validateOperationEnvelope = (response) => {
    const data = readResponseData(response);
    if (
        !data ||
        data.ok !== true ||
        typeof data.operation_id !== 'string' ||
        !data.operation_id.trim()
    ) {
        throw new AccountAbstractionError('El backend no preparó una operación identificable.');
    }
    return { data, operation: deserializeUserOperation(data.user_operation) };
};

/**
 * Full client flow: derive Safe, ask backend/Pimlico for sponsorship, validate
 * every immutable field, sign locally, submit through the backend and poll.
 */
export const mintMembershipWithSafe = async ({
    proof,
    provider,
    getConfig,
    prepareMint,
    submitMint,
    getOperation,
    pollIntervalMs = 1500,
    timeoutMs = 120000,
}) => {
    if (![getConfig, prepareMint, submitMint, getOperation].every((fn) => typeof fn === 'function')) {
        throw new AccountAbstractionError('Falta el transporte backend ERC-4337.');
    }
    const normalizedProof = normalizeMintProof(proof);
    const config = normalizeAccountAbstractionConfig(await getConfig());
    if (normalizedProof.chainId !== config.chainId) {
        throw new AccountAbstractionError('La prueba ZK y el patrocinio pertenecen a redes distintas.');
    }
    const call = buildSafeMintCall(normalizedProof);
    const { safeAccount, draft } = await buildSafeUserOperationDraft({
        provider,
        ownerAddress: normalizedProof.walletAddress,
        config,
        call,
    });

    const prepareResponse = await prepareMint({
        owner_address: normalizedProof.walletAddress,
        safe_address: safeAccount.address,
        chain_id: String(config.chainId),
        entry_point: config.entryPoint,
        account: {
            type: 'safe',
            version: SAFE_VERSION,
            salt_nonce: SAFE_SALT_NONCE.toString(),
            safe_4337_module_address: config.safe4337ModuleAddress,
            use_multi_send_for_setup: false,
        },
        mint: {
            wallet_address: normalizedProof.walletAddress,
            pA: normalizedProof.pA,
            pB: normalizedProof.pB,
            pC: normalizedProof.pC,
            nullifier_hash: normalizedProof.nullifierHash,
            identity_root: normalizedProof.identityRoot,
        },
        user_operation: serializeUserOperation(draft),
    });
    const { data: preparedData, operation: preparedOperation } =
        validateOperationEnvelope(prepareResponse);
    assertPreparedOperationMatchesDraft(preparedOperation, draft, config);

    let signature;
    try {
        await verifyActiveProvider(
            provider,
            normalizedProof.walletAddress,
            config.chainId
        );
        signature = normalizeHex(
            await safeAccount.signUserOperation({
                ...preparedOperation,
                chainId: config.chainId,
            }),
            'La firma SafeOp devuelta por MetaMask',
            77
        );
    } catch (error) {
        if (error?.code === 4001 || error?.cause?.code === 4001) {
            throw new AccountAbstractionError(
                'La firma de la Smart Account fue rechazada.',
                'USER_REJECTED_SIGNATURE'
            );
        }
        throw error;
    }
    const signedOperation = { ...preparedOperation, signature };
    const expectedUserOperationHash = getUserOperationHash({
        userOperation: signedOperation,
        entryPointAddress: config.entryPoint,
        entryPointVersion: ENTRY_POINT_VERSION,
        chainId: config.chainId,
    }).toLowerCase();
    const submitResponse = await submitMint({
        operation_id: preparedData.operation_id,
        owner_address: normalizedProof.walletAddress,
        safe_address: safeAccount.address,
        entry_point: config.entryPoint,
        user_operation: serializeUserOperation(signedOperation),
    });
    const submitted = readResponseData(submitResponse);
    if (!submitted || submitted.ok !== true) {
        throw new AccountAbstractionError(
            submitted?.error || 'El bundler rechazó la UserOperation firmada.'
        );
    }
    const userOperationHash = assertExpectedUserOperationHash(
        submitted.user_operation_hash,
        expectedUserOperationHash
    );
    const immediateConfirmation = readConfirmedMint(submitted);
    if (immediateConfirmation) {
        return {
            data: {
                ...immediateConfirmation,
                user_operation_hash: userOperationHash,
            },
        };
    }

    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
        const status = readResponseData(await getOperation(userOperationHash));
        if (status?.status === 'failed' || status?.ok === false) {
            throw new AccountAbstractionError(
                status?.error || 'La UserOperation falló antes de confirmar.'
            );
        }
        if (status?.user_operation_hash != null) {
            assertExpectedUserOperationHash(
                status.user_operation_hash,
                expectedUserOperationHash
            );
        }
        const confirmation = readConfirmedMint(status);
        if (confirmation) {
            return {
                data: {
                    ...confirmation,
                    ok: true,
                    user_operation_hash: userOperationHash,
                },
            };
        }
    }
    throw new AccountAbstractionError(
        `La operación ${userOperationHash} sigue pendiente; no se reenviará automáticamente.`,
        'USER_OPERATION_PENDING'
    );
};
