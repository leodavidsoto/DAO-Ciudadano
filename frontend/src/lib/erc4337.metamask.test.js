import { SafeSmartAccount } from 'permissionless/accounts/safe';
import { toOwner } from 'permissionless/utils';
import { concatHex, getAddress, keccak256, size, stringToHex, toHex } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import {
    CANONICAL_ENTRY_POINT_V07,
    CANONICAL_SAFE_4337_MODULE_V141_V07,
    ENTRY_POINT_VERSION,
    SAFE_VERSION,
} from './erc4337';

const SAFE = getAddress('0x2222222222222222222222222222222222222222');
const FACTORY = getAddress('0x4444444444444444444444444444444444444444');
const PAYMASTER = getAddress('0x5555555555555555555555555555555555555555');

test('the installed Safe client asks MetaMask to sign the final SafeOp via EIP-712', async () => {
    // Ephemeral test-only owner: no private-key-shaped fixture is stored in the
    // repository and this account has no authority outside this test process.
    const ownerAccount = privateKeyToAccount(
        keccak256(stringToHex('dao-ciudadana-metamask-safeop-unit-fixture-no-value'))
    );
    const signingRequests = [];
    const provider = {
        isMetaMask: true,
        request: jest.fn(async ({ method, params }) => {
            if (method !== 'eth_signTypedData_v4') {
                throw new Error(`Unexpected provider method ${method}`);
            }
            signingRequests.push({ method, params });
            const typedData = JSON.parse(params[1]);
            const types = { ...typedData.types };
            delete types.EIP712Domain;
            return ownerAccount.signTypedData({
                domain: typedData.domain,
                types,
                primaryType: typedData.primaryType,
                message: typedData.message,
            });
        }),
    };
    const owner = await toOwner({
        owner: provider,
        address: ownerAccount.address,
    });
    const operation = {
        sender: SAFE,
        nonce: 4n,
        factory: FACTORY,
        factoryData: '0x1234',
        callData: '0xabcdef',
        callGasLimit: 200_000n,
        verificationGasLimit: 300_000n,
        preVerificationGas: 50_000n,
        maxFeePerGas: 2_000_000_000n,
        maxPriorityFeePerGas: 1_000_000_000n,
        paymaster: PAYMASTER,
        paymasterData: '0xcafe',
        paymasterVerificationGasLimit: 100_000n,
        paymasterPostOpGasLimit: 100_000n,
    };

    const packedSignature = await SafeSmartAccount.signUserOperation({
        ...operation,
        account: owner,
        owners: [owner],
        version: SAFE_VERSION,
        entryPoint: {
            address: CANONICAL_ENTRY_POINT_V07,
            version: ENTRY_POINT_VERSION,
        },
        chainId: 11155111,
        safe4337ModuleAddress: CANONICAL_SAFE_4337_MODULE_V141_V07,
    });

    expect(signingRequests).toHaveLength(1);
    const [{ method, params }] = signingRequests;
    expect(method).toBe('eth_signTypedData_v4');
    expect(getAddress(params[0])).toBe(ownerAccount.address);

    const typedData = JSON.parse(params[1]);
    expect(typedData.primaryType).toBe('SafeOp');
    expect(Number(typedData.domain.chainId)).toBe(11155111);
    expect(getAddress(typedData.domain.verifyingContract))
        .toBe(CANONICAL_SAFE_4337_MODULE_V141_V07);
    expect(getAddress(typedData.message.safe)).toBe(SAFE);
    expect(getAddress(typedData.message.entryPoint)).toBe(CANONICAL_ENTRY_POINT_V07);
    expect(typedData.message.callData).toBe(operation.callData);
    expect(typedData.message.initCode).toBe(
        concatHex([FACTORY, operation.factoryData]).toLowerCase()
    );
    expect(typedData.message.paymasterAndData).toBe(
        concatHex([
            PAYMASTER,
            toHex(operation.paymasterVerificationGasLimit, { size: 16 }),
            toHex(operation.paymasterPostOpGasLimit, { size: 16 }),
            operation.paymasterData,
        ]).toLowerCase()
    );
    expect(BigInt(typedData.message.callGasLimit)).toBe(operation.callGasLimit);
    expect(BigInt(typedData.message.maxFeePerGas)).toBe(operation.maxFeePerGas);
    expect(typedData.message.validAfter).toBe(0);
    expect(typedData.message.validUntil).toBe(0);

    // Safe4337Module expects uint48 validAfter + uint48 validUntil + 65-byte
    // owner signature. This proves the final artifact came from that request.
    expect(size(packedSignature)).toBe(77);
    expect(packedSignature.slice(2, 26)).toBe('0'.repeat(24));
});
