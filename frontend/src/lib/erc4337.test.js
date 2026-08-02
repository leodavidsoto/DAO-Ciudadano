import { decodeFunctionData } from 'viem';
import { getUserOperationHash } from 'viem/account-abstraction';
import { toSafeSmartAccount } from 'permissionless/accounts';
import { toOwner } from 'permissionless/utils';
import {
    AccountAbstractionError,
    CANONICAL_ENTRY_POINT_V07,
    CANONICAL_SAFE_4337_MODULE_V141_V07,
    buildSafeMintCall,
    deserializeUserOperation,
    mintMembershipWithSafe,
    normalizeAccountAbstractionConfig,
} from './erc4337';

jest.mock('permissionless/accounts', () => ({
    toSafeSmartAccount: jest.fn(),
}));
jest.mock('permissionless/utils', () => ({
    toOwner: jest.fn(),
}));

const OWNER = '0x1111111111111111111111111111111111111111';
const SAFE = '0x2222222222222222222222222222222222222222';
const SBT = '0x3333333333333333333333333333333333333333';
const FACTORY = '0x4444444444444444444444444444444444444444';
const PAYMASTER = '0x5555555555555555555555555555555555555555';
const PINNED_OWNER = { address: OWNER, type: 'local' };

const proof = {
    walletAddress: OWNER,
    membershipContract: SBT,
    chainId: '11155111',
    pA: ['1', '2'],
    pB: [['3', '4'], ['5', '6']],
    pC: ['7', '8'],
    nullifierHash: `0x${'09'.repeat(32)}`,
    identityRoot: '10',
};

const configResponse = {
    data: {
        enabled: true,
        sponsorship_enabled: true,
        account_type: 'safe',
        bundler_provider: 'pimlico',
        paymaster_provider: 'pimlico',
        paymaster: PAYMASTER,
        safe_version: '1.4.1',
        safe_salt_nonce: '0',
        use_multi_send_for_setup: false,
        safe_4337_module_address: CANONICAL_SAFE_4337_MODULE_V141_V07,
        entry_point: CANONICAL_ENTRY_POINT_V07,
        entry_point_version: '0.7',
        chain_id: '11155111',
        chain_name: 'Sepolia',
    },
};

const provider = {
    request: jest.fn(async ({ method }) => {
        if (method === 'eth_accounts') return [OWNER];
        if (method === 'eth_chainId') return '0xaa36a7';
        throw new Error(`Unexpected method ${method}`);
    }),
};

const createSafeFixture = () => ({
    address: SAFE,
    encodeCalls: jest.fn(async () => '0xabcdef'),
    getFactoryArgs: jest.fn(async () => ({ factory: FACTORY, factoryData: '0x1234' })),
    getNonce: jest.fn(async () => 4n),
    getStubSignature: jest.fn(async () => '0xaaaa'),
    signUserOperation: jest.fn(async () => '0xbbbb'),
});

const sponsoredOperation = {
    sender: SAFE,
    nonce: '0x4',
    factory: FACTORY,
    factoryData: '0x1234',
    callData: '0xabcdef',
    callGasLimit: '0x30d40',
    verificationGasLimit: '0x493e0',
    preVerificationGas: '0xc350',
    maxFeePerGas: '0x77359400',
    maxPriorityFeePerGas: '0x3b9aca00',
    paymaster: PAYMASTER,
    paymasterData: '0xcafe',
    paymasterVerificationGasLimit: '0x186a0',
    paymasterPostOpGasLimit: '0x186a0',
    signature: '0xaaaa',
};

const expectedUserOperationHash = (operation = sponsoredOperation) =>
    getUserOperationHash({
        userOperation: deserializeUserOperation(operation),
        entryPointAddress: CANONICAL_ENTRY_POINT_V07,
        entryPointVersion: '0.7',
        chainId: 11155111,
    });

beforeEach(() => {
    jest.clearAllMocks();
    toOwner.mockResolvedValue(PINNED_OWNER);
    provider.request.mockImplementation(async ({ method }) => {
        if (method === 'eth_accounts') return [OWNER];
        if (method === 'eth_chainId') return '0xaa36a7';
        throw new Error(`Unexpected method ${method}`);
    });
});

test('encodes the wallet-bound ZK mint as a zero-value Safe call', () => {
    const call = buildSafeMintCall(proof);
    const decoded = decodeFunctionData({
        abi: [{
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
        }],
        data: call.data,
    });

    expect(call.to).toBe(SBT);
    expect(call.value).toBe(0n);
    expect(decoded.functionName).toBe('mintMembership');
    expect(decoded.args).toEqual([
        OWNER,
        [1n, 2n],
        [[3n, 4n], [5n, 6n]],
        [7n, 8n],
        proof.nullifierHash,
        10n,
    ]);
});

test('accepts Groth16 proof coordinates from the BN254 base field', () => {
    const scalarField =
        '21888242871839275222246405745257275088548364400416034343698204186575808495617';
    const call = buildSafeMintCall({
        ...proof,
        pA: [scalarField, '2'],
    });
    const decoded = decodeFunctionData({
        abi: [{
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
        }],
        data: call.data,
    });

    expect(decoded.args[1][0]).toBe(BigInt(scalarField));
});

test('rejects a nullifier that is hexadecimal but not bytes32', () => {
    expect(() => buildSafeMintCall({
        ...proof,
        nullifierHash: '0x01',
    })).toThrow(/nullifier.*hexadecimal/i);
});

test('rejects non-canonical or disabled account-abstraction config', () => {
    expect(() => normalizeAccountAbstractionConfig({
        ...configResponse.data,
        entry_point: SBT,
    })).toThrow(/canónico/i);
    expect(() => normalizeAccountAbstractionConfig({
        ...configResponse.data,
        sponsorship_enabled: false,
    })).toThrow(/no habilitó/i);
    expect(() => normalizeAccountAbstractionConfig({
        ...configResponse.data,
        safe_4337_module_address: SBT,
    })).toThrow(/módulo Safe4337/i);
    expect(() => normalizeAccountAbstractionConfig({
        ...configResponse.data,
        safe_4337_module_address: undefined,
    })).toThrow(/módulo Safe4337/i);
});

test('validates sponsorship, signs final fields locally and submits once', async () => {
    const safe = createSafeFixture();
    toSafeSmartAccount.mockResolvedValue(safe);
    const prepareMint = jest.fn(async () => ({
        data: {
            ok: true,
            operation_id: 'operation-1',
            user_operation: sponsoredOperation,
        },
    }));
    const submitMint = jest.fn(async () => ({
        data: {
            ok: true,
            user_operation_hash: expectedUserOperationHash(),
            tx_hash: `0x${'cd'.repeat(32)}`,
            token_id: 7,
        },
    }));
    const result = await mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint,
        submitMint,
        getOperation: jest.fn(),
    });

    expect(safe.encodeCalls).toHaveBeenCalledWith([
        expect.objectContaining({ to: SBT, value: 0n }),
    ]);
    expect(prepareMint).toHaveBeenCalledTimes(1);
    expect(prepareMint.mock.calls[0][0].account).toEqual(expect.objectContaining({
        safe_4337_module_address: CANONICAL_SAFE_4337_MODULE_V141_V07,
    }));
    expect(toOwner).toHaveBeenCalledWith({
        owner: provider,
        address: OWNER,
    });
    expect(toSafeSmartAccount).toHaveBeenCalledWith(expect.objectContaining({
        owners: [PINNED_OWNER],
        safe4337ModuleAddress: CANONICAL_SAFE_4337_MODULE_V141_V07,
    }));
    expect(safe.signUserOperation).toHaveBeenCalledWith(expect.objectContaining({
        sender: SAFE,
        callData: '0xabcdef',
        paymaster: PAYMASTER,
        chainId: 11155111,
    }));
    expect(submitMint).toHaveBeenCalledTimes(1);
    expect(submitMint.mock.calls[0][0].user_operation.signature).toBe('0xbbbb');
    expect(result.data).toEqual(expect.objectContaining({ ok: true, token_id: 7 }));
});

test('refuses a well-formed hash for a different UserOperation', async () => {
    const safe = createSafeFixture();
    toSafeSmartAccount.mockResolvedValue(safe);
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(async () => ({
            data: {
                ok: true,
                operation_id: 'operation-1',
                user_operation: sponsoredOperation,
            },
        })),
        submitMint: jest.fn(async () => ({
            data: {
                ok: true,
                user_operation_hash: `0x${'ab'.repeat(32)}`,
            },
        })),
        getOperation: jest.fn(),
    })).rejects.toThrow(/UserOperation distinta/i);
});

test('refuses a UserOperation hash that is not bytes32', async () => {
    const safe = createSafeFixture();
    toSafeSmartAccount.mockResolvedValue(safe);
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(async () => ({
            data: {
                ok: true,
                operation_id: 'operation-1',
                user_operation: sponsoredOperation,
            },
        })),
        submitMint: jest.fn(async () => ({
            data: {
                ok: true,
                user_operation_hash: '0x01',
            },
        })),
        getOperation: jest.fn(),
    })).rejects.toThrow(/hash de UserOperation.*hexadecimal/i);
});

test.each([
    {
        confirmation: { tx_hash: '0x1234', token_id: 7 },
        expectedError: /hash de transacción.*hexadecimal/i,
    },
    {
        confirmation: { tx_hash: `0x${'cd'.repeat(32)}`, token_id: 0 },
        expectedError: /tokenId.*válido/i,
    },
    {
        confirmation: { tx_hash: `0x${'cd'.repeat(32)}` },
        expectedError: /confirmación on-chain está incompleta/i,
    },
])('rejects malformed mint confirmations: $confirmation', async ({
    confirmation,
    expectedError,
}) => {
    const safe = createSafeFixture();
    toSafeSmartAccount.mockResolvedValue(safe);
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(async () => ({
            data: {
                ok: true,
                operation_id: 'operation-1',
                user_operation: sponsoredOperation,
            },
        })),
        submitMint: jest.fn(async () => ({
            data: {
                ok: true,
                user_operation_hash: expectedUserOperationHash(),
                ...confirmation,
            },
        })),
        getOperation: jest.fn(),
    })).rejects.toThrow(expectedError);
});

test('refuses a sponsored operation whose Safe calldata was changed', async () => {
    const safe = createSafeFixture();
    toSafeSmartAccount.mockResolvedValue(safe);
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(async () => ({
            data: {
                ok: true,
                operation_id: 'operation-1',
                user_operation: { ...sponsoredOperation, callData: '0xdeadbeef' },
            },
        })),
        submitMint: jest.fn(),
        getOperation: jest.fn(),
    })).rejects.toThrow(/alteró la llamada/i);
    expect(safe.signUserOperation).not.toHaveBeenCalled();
});

test('fails before Safe derivation when the active wallet changed', async () => {
    provider.request.mockImplementation(async ({ method }) =>
        method === 'eth_accounts'
            ? ['0x9999999999999999999999999999999999999999']
            : '0xaa36a7'
    );
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(),
        submitMint: jest.fn(),
        getOperation: jest.fn(),
    })).rejects.toBeInstanceOf(AccountAbstractionError);
    expect(toSafeSmartAccount).not.toHaveBeenCalled();
});

test('does not submit when the citizen rejects the final Safe signature', async () => {
    const safe = createSafeFixture();
    safe.signUserOperation.mockRejectedValue({ code: 4001 });
    toSafeSmartAccount.mockResolvedValue(safe);
    const submitMint = jest.fn();
    await expect(mintMembershipWithSafe({
        proof,
        provider,
        getConfig: jest.fn(async () => configResponse),
        prepareMint: jest.fn(async () => ({
            data: {
                ok: true,
                operation_id: 'operation-1',
                user_operation: sponsoredOperation,
            },
        })),
        submitMint,
        getOperation: jest.fn(),
    })).rejects.toMatchObject({ code: 'USER_REJECTED_SIGNATURE' });
    expect(submitMint).not.toHaveBeenCalled();
});
