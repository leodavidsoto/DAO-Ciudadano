import {
    Interface,
    Wallet,
    getAddress,
    keccak256,
    toUtf8Bytes,
    verifyMessage,
} from 'ethers';
import { Keypair, PrivKey } from 'maci-domainobjs';
import { poseidon2 } from 'poseidon-lite';
import { getUserOperationHash } from 'viem/account-abstraction';

// Derive throwaway keys at runtime so the repository contains no private-key
// shaped fixture. These domain strings have no authority outside this test.
const fixtureWallet = (role) => new Wallet(
    keccak256(toUtf8Bytes(`dao-ciudadana-e2e-${role}-fixture-no-value`))
);
const userWallet = fixtureWallet('citizen');
const issuerWallet = fixtureWallet('issuer');
const coordinatorKeypair = new Keypair(new PrivKey(123456789n));
const coordinatorPublicKey = Object.freeze({
    x: coordinatorKeypair.pubKey.rawPubKey[0].toString(),
    y: coordinatorKeypair.pubKey.rawPubKey[1].toString(),
});
const coordinatorKeyHash =
    `0x${poseidon2(coordinatorKeypair.pubKey.rawPubKey).toString(16).padStart(64, '0')}`;

export const E2E_FIXTURE = Object.freeze({
    // Deterministic public test fixtures only. They hold no funds or authority.
    userAddress: userWallet.address,
    issuerAddress: issuerWallet.address,
    membershipContract: getAddress('0x1000000000000000000000000000000000000001'),
    maciCoordinator: getAddress('0x2000000000000000000000000000000000000002'),
    maciTallyVerifier: getAddress('0x3000000000000000000000000000000000000003'),
    paymaster: getAddress('0x4000000000000000000000000000000000000004'),
    entryPoint: getAddress('0x0000000071727De22E5E9d8BAf0edAc6f37da032'),
    safe4337Module: getAddress('0x75cf11467937ce3F2f357CE24ffc3DBF8fD5c226'),
    safeProxyFactory: getAddress('0x4e1DCf7AD4e460CfD30791CCC4F9c8a4f820ec67'),
    chainId: 11155111,
    membershipScope: '7348821',
    identityGrant: 'e2e-fixture-grant-never-production',
    proposalId: 'proposal-e2e-zk-maci',
    pollId: '7',
    coordinatorPublicKey,
    coordinatorKeyHash,
    txHash: `0x${'7e'.repeat(32)}`,
    tokenId: 7001,
    maciMessageId: 'e2e-fixture-maci-message-0001',
});

export const getCoordinatorKeypair = () => coordinatorKeypair.copy();

const membershipInterface = new Interface([
    'function membershipScope() view returns (uint256)',
    'function isIdentityRootApproved(uint256 identityRoot) view returns (bool)',
]);
const coordinatorInterface = new Interface([
    'function coordinatorPubKeyX() view returns (uint256)',
    'function coordinatorPubKeyY() view returns (uint256)',
    'function tallyVerifier() view returns (address)',
]);
const safeFactoryInterface = new Interface([
    'function proxyCreationCode() view returns (bytes)',
]);
const entryPointInterface = new Interface([
    'function getNonce(address sender, uint192 key) view returns (uint256)',
]);

const selectorResult = (contractInterface, functionName, values) => ({
    selector: contractInterface.getFunction(functionName).selector,
    result: contractInterface.encodeFunctionResult(functionName, values),
});

const E2E_SESSION_COOKIE = 'dao_session=e2e-http-only-session';
const E2E_CSRF_TOKEN = 'c'.repeat(64);
const E2E_OIDC_STATE = 'state_e2e_1234567890abcdefghijklmnopqrstuvwxyz';
const E2E_OIDC_CODE = 'e2e-one-time-authorization-code';
const E2E_OIDC_BINDING_COOKIE = 'dao_oidc_binding=e2e-browser-binding';

const buildSiweChallenge = (address) => {
    const nonce = 'E2EFLOW20260801';
    const issuedAt = '2026-08-01T12:00:00.000Z';
    const expirationTime = '2099-01-01T00:00:00.000Z';
    const message = [
        '127.0.0.1:3005 wants you to sign in with your Ethereum account:',
        getAddress(address),
        '',
        'Autoriza el fixture local E2E de DAO Ciudadana.',
        '',
        'URI: http://127.0.0.1:3005',
        'Version: 1',
        `Chain ID: ${E2E_FIXTURE.chainId}`,
        `Nonce: ${nonce}`,
        `Issued At: ${issuedAt}`,
        `Expiration Time: ${expirationTime}`,
    ].join('\n');
    return { nonce, message, expires_at: expirationTime };
};

const toIdentityRoot = (commitment) => {
    let root = BigInt(commitment);
    for (let level = 0; level < 25; level += 1) {
        root = poseidon2([root, 0n]);
    }
    return root.toString();
};

const canonicalCredentialMessage = ({ recipient, identityRoot, scope, commitment }) => [
    'DAO Ciudadana Identity Credential v1',
    `recipient:${getAddress(recipient).toLowerCase()}`,
    `identityRoot:${identityRoot}`,
    `scope:${scope}`,
    `commitment:${commitment}`,
].join('\n');

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

const deserializeUserOperation = (operation) => Object.fromEntries(
    Object.entries(operation).map(([key, value]) => [
        key,
        numericUserOperationFields.has(key) ? BigInt(value) : value,
    ])
);

const corsHeaders = (route) => {
    const origin = route.request().headers().origin;
    return origin ? {
        'access-control-allow-origin': origin,
        'access-control-allow-credentials': 'true',
        vary: 'Origin',
    } : {};
};

const jsonResponse = (route, body, status = 200, headers = {}) => route.fulfill({
    status,
    contentType: 'application/json',
    headers: {
        'cache-control': 'no-store',
        ...corsHeaders(route),
        ...headers,
    },
    body: JSON.stringify(body),
});

export const installEip1193Fixture = async (page) => {
    await page.exposeFunction('__e2eSignWalletPayload', async ({ method, params }) => {
        if (method === 'personal_sign' || method === 'eth_sign') {
            const payload = method === 'personal_sign' ? params[0] : params[1];
            const bytes = payload.startsWith('0x')
                ? Buffer.from(payload.slice(2), 'hex')
                : Buffer.from(payload, 'utf8');
            return userWallet.signMessage(bytes);
        }
        if (method === 'eth_signTypedData_v4') {
            const typedData = typeof params[1] === 'string'
                ? JSON.parse(params[1])
                : params[1];
            const types = { ...typedData.types };
            delete types.EIP712Domain;
            return userWallet.signTypedData(
                typedData.domain,
                types,
                typedData.message
            );
        }
        throw new Error(`Unsupported E2E signing method: ${method}`);
    });

    const rpcFixture = {
        userAddress: E2E_FIXTURE.userAddress,
        chainHex: `0x${E2E_FIXTURE.chainId.toString(16)}`,
        deployedContracts: [
            E2E_FIXTURE.membershipContract,
            E2E_FIXTURE.maciCoordinator,
            E2E_FIXTURE.maciTallyVerifier,
            E2E_FIXTURE.entryPoint,
            E2E_FIXTURE.safe4337Module,
            E2E_FIXTURE.safeProxyFactory,
        ].map((address) => address.toLowerCase()),
        callResults: [
            selectorResult(
                membershipInterface,
                'membershipScope',
                [BigInt(E2E_FIXTURE.membershipScope)]
            ),
            selectorResult(
                membershipInterface,
                'isIdentityRootApproved',
                [true]
            ),
            selectorResult(
                coordinatorInterface,
                'coordinatorPubKeyX',
                [BigInt(E2E_FIXTURE.coordinatorPublicKey.x)]
            ),
            selectorResult(
                coordinatorInterface,
                'coordinatorPubKeyY',
                [BigInt(E2E_FIXTURE.coordinatorPublicKey.y)]
            ),
            selectorResult(
                coordinatorInterface,
                'tallyVerifier',
                [E2E_FIXTURE.maciTallyVerifier]
            ),
            selectorResult(
                safeFactoryInterface,
                'proxyCreationCode',
                ['0x6080604052600080fd']
            ),
            selectorResult(entryPointInterface, 'getNonce', [0n]),
        ],
    };

    await page.addInitScript((fixture) => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_address');
        window.__E2E_RPC_LOG__ = [];

        const listeners = new Map();
        const provider = {
            isMetaMask: true,
            on(event, handler) {
                const handlers = listeners.get(event) || new Set();
                handlers.add(handler);
                listeners.set(event, handlers);
                return provider;
            },
            removeListener(event, handler) {
                listeners.get(event)?.delete(handler);
                return provider;
            },
            async request({ method, params = [] }) {
                const rpcCall = { method, params };
                window.__E2E_RPC_LOG__.push(rpcCall);
                if (['personal_sign', 'eth_sign', 'eth_signTypedData_v4'].includes(method)) {
                    const result = await window.__e2eSignWalletPayload({ method, params });
                    // Preserve the throwaway signature in the browser-only log
                    // so the spec can independently recover the signing owner.
                    rpcCall.result = result;
                    return result;
                }
                switch (method) {
                    case 'eth_accounts':
                    case 'eth_requestAccounts':
                        return [fixture.userAddress];
                    case 'eth_chainId':
                        return fixture.chainHex;
                    case 'net_version':
                        return String(parseInt(fixture.chainHex, 16));
                    case 'eth_getBalance':
                        return '0xde0b6b3a7640000';
                    case 'eth_blockNumber':
                        return '0x1';
                    case 'eth_gasPrice':
                    case 'eth_maxPriorityFeePerGas':
                        return '0x3b9aca00';
                    case 'eth_estimateGas':
                        return '0x7a120';
                    case 'eth_getTransactionCount':
                        return '0x0';
                    case 'wallet_switchEthereumChain':
                        return null;
                    case 'eth_getCode': {
                        const address = String(params[0] || '').toLowerCase();
                        return fixture.deployedContracts.includes(address)
                            ? '0x60006000'
                            : '0x';
                    }
                    case 'eth_call': {
                        const data = String(params[0]?.data || '0x');
                        const selector = data.slice(0, 10).toLowerCase();
                        const match = fixture.callResults.find(
                            (candidate) => candidate.selector.toLowerCase() === selector
                        );
                        if (match) return match.result;
                        throw new Error(
                            `E2E fixture has no eth_call result for selector ${selector}`
                        );
                    }
                    case 'eth_getBlockByNumber':
                        return {
                            number: '0x1',
                            hash: `0x${'11'.repeat(32)}`,
                            parentHash: `0x${'22'.repeat(32)}`,
                            nonce: '0x0000000000000000',
                            sha3Uncles: `0x${'00'.repeat(32)}`,
                            logsBloom: `0x${'00'.repeat(256)}`,
                            transactionsRoot: `0x${'00'.repeat(32)}`,
                            stateRoot: `0x${'00'.repeat(32)}`,
                            receiptsRoot: `0x${'00'.repeat(32)}`,
                            miner: '0x0000000000000000000000000000000000000000',
                            difficulty: '0x0',
                            totalDifficulty: '0x0',
                            extraData: '0x',
                            size: '0x0',
                            gasLimit: '0x1c9c380',
                            gasUsed: '0x0',
                            timestamp: '0x1',
                            transactions: [],
                            uncles: [],
                            baseFeePerGas: '0x3b9aca00',
                        };
                    default:
                        throw new Error(`E2E fixture has no RPC handler for ${method}`);
                }
            },
        };

        // Keep a browser-only handle to the provider that established SIWE.
        // The spec later replaces window.ethereum with a trap provider; a
        // correct mint must continue through this pinned instance.
        window.__E2E_PINNED_PROVIDER__ = provider;
        Object.defineProperty(window, 'ethereum', {
            configurable: true,
            enumerable: true,
            value: provider,
            writable: true,
        });
    }, rpcFixture);
};

export const installBackendFixture = async (page) => {
    const state = {
        identityCredentialRequests: [],
        preparedMintRequests: [],
        submittedMintRequests: [],
        registeredMaciKeys: [],
        encryptedBallots: [],
        siweChallenges: [],
        siweVerifications: [],
        sessionReads: [],
        logouts: [],
        oidcCallbackRequests: [],
        identityGrantConsumed: false,
    };

    await page.route('https://clave-unica.fixture.invalid/authorize**', async (route) => {
        const requestUrl = new URL(route.request().url());
        if (requestUrl.searchParams.get('state') !== E2E_OIDC_STATE) {
            return route.fulfill({ status: 400, body: 'Invalid fixture state' });
        }
        return route.fulfill({
            status: 302,
            headers: {
                location:
                    `http://127.0.0.1:3005/unete/clave-unica/callback` +
                    `?code=${E2E_OIDC_CODE}&state=${E2E_OIDC_STATE}`,
                'cache-control': 'no-store',
            },
            body: '',
        });
    });

    await page.route('**/api/**', async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname;
        const method = request.method();
        const headers = await request.allHeaders();
        const hasSessionCookie = (headers.cookie || '')
            .split(';')
            .map((value) => value.trim())
            .includes(E2E_SESSION_COOKIE);
        const hasCsrfHeader = headers['x-csrf-token'] === E2E_CSRF_TOKEN;
        const hasOidcBinding = (headers.cookie || '')
            .split(';')
            .map((value) => value.trim())
            .includes(E2E_OIDC_BINDING_COOKIE);

        if (method === 'OPTIONS') {
            return route.fulfill({
                status: 204,
                headers: {
                    ...corsHeaders(route),
                    'access-control-allow-methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
                    'access-control-allow-headers':
                        headers['access-control-request-headers'] || 'content-type, x-csrf-token',
                    'access-control-max-age': '600',
                },
            });
        }

        if (method === 'GET' && path === '/api/dashboard/stats') {
            return jsonResponse(route, { total_members: 1, recent_joins: 1 });
        }
        if (method === 'GET' && path === '/api/auth/clave-unica/status') {
            return jsonResponse(route, {
                available: true,
                protocol_version: 'clave-unica-oidc-pkce-v1',
                pkce_method: 'S256',
                browser_bound: true,
                credential_exchange_browser_bound: true,
                callback_idempotent: true,
                grant_single_use: true,
                redirect_transport: 'frontend-post',
                grant_ttl_seconds: 300,
            });
        }
        if (method === 'POST' && path === '/api/auth/clave-unica/authorize') {
            return jsonResponse(route, {
                authorization_url:
                    `https://clave-unica.fixture.invalid/authorize` +
                    `?client_id=e2e&state=${E2E_OIDC_STATE}`,
                state: E2E_OIDC_STATE,
                expires_in: 600,
            }, 200, {
                'set-cookie':
                    `${E2E_OIDC_BINDING_COOKIE}; Path=/; HttpOnly; SameSite=Lax; Max-Age=600`,
            });
        }
        if (method === 'POST' && path === '/api/auth/clave-unica/callback') {
            const body = request.postDataJSON();
            state.oidcCallbackRequests.push({ body, cookie: headers.cookie || null });
            if (
                !hasOidcBinding ||
                body.code !== E2E_OIDC_CODE ||
                body.state !== E2E_OIDC_STATE
            ) {
                return jsonResponse(route, { detail: 'Fixture OIDC binding rejected' }, 401);
            }
            return jsonResponse(route, {
                ok: true,
                identity_grant: E2E_FIXTURE.identityGrant,
                identity_grant_expires_in: 300,
                assurance_level: 'CLAVE_UNICA',
                name: 'Ciudadana E2E',
            });
        }
        if (method === 'POST' && path === '/api/wallet/challenge') {
            const body = request.postDataJSON();
            const challenge = buildSiweChallenge(body.address);
            state.siweChallenges.push({ body, challenge });
            return jsonResponse(route, challenge);
        }
        if (method === 'POST' && path === '/api/wallet/verify') {
            const body = request.postDataJSON();
            const issued = state.siweChallenges.find(
                ({ challenge }) => challenge.nonce === body.nonce
            );
            const recoveredAddress = issued
                ? verifyMessage(issued.challenge.message, body.signature)
                : null;
            state.siweVerifications.push({ body, recoveredAddress });
            if (
                !issued ||
                recoveredAddress.toLowerCase() !== body.address.toLowerCase()
            ) {
                return jsonResponse(route, { detail: 'Fixture SIWE signature rejected' }, 401);
            }
            if (body.session_transport !== 'cookie') {
                return jsonResponse(route, { detail: 'Fixture requires cookie transport' }, 422);
            }
            return jsonResponse(route, {
                token: null,
                address: recoveredAddress.toLowerCase(),
                expires_in: 3600,
                csrf_token: E2E_CSRF_TOKEN,
            }, 200, {
                'set-cookie': `${E2E_SESSION_COOKIE}; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600`,
            });
        }
        if (method === 'GET' && path === '/api/wallet/session') {
            state.sessionReads.push({ cookie: headers.cookie || null });
            if (!hasSessionCookie || state.siweVerifications.length === 0) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            return jsonResponse(route, {
                address: E2E_FIXTURE.userAddress.toLowerCase(),
                csrf_token: E2E_CSRF_TOKEN,
            });
        }
        if (method === 'POST' && path === '/api/wallet/logout') {
            state.logouts.push({
                cookie: headers.cookie || null,
                csrf: headers['x-csrf-token'] || null,
            });
            return jsonResponse(route, {
                ok: true,
                message: 'Sesión E2E cerrada.',
            }, 200, {
                'set-cookie': 'dao_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0',
            });
        }
        if (method === 'POST' && path === '/api/auth/liveness') {
            return jsonResponse(route, {
                ok: true,
                score: null,
                analysis: 'Resultado controlado del fixture E2E; no es biometría.',
            });
        }
        if (method === 'GET' && path.startsWith('/api/membership/member/')) {
            if (!hasSessionCookie) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            return jsonResponse(route, { found: false, member: null });
        }
        if (method === 'POST' && path === '/api/auth/identity-credential') {
            if (!hasSessionCookie || !hasOidcBinding) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            if (!hasCsrfHeader) {
                return jsonResponse(route, { detail: 'Fixture CSRF rejected' }, 403);
            }
            const body = request.postDataJSON();
            state.identityCredentialRequests.push(body);
            if (body.identity_grant !== E2E_FIXTURE.identityGrant) {
                return jsonResponse(route, { detail: 'Fixture grant rejected' }, 403);
            }
            if (state.identityGrantConsumed) {
                return jsonResponse(route, { detail: 'Fixture grant already consumed' }, 409);
            }
            state.identityGrantConsumed = true;
            const identityRoot = toIdentityRoot(body.identity_commitment);
            const signature = await issuerWallet.signMessage(
                canonicalCredentialMessage({
                    recipient: body.wallet_address,
                    identityRoot,
                    scope: body.membership_scope,
                    commitment: body.identity_commitment,
                })
            );
            const recoveredIssuer = verifyMessage(
                canonicalCredentialMessage({
                    recipient: body.wallet_address,
                    identityRoot,
                    scope: body.membership_scope,
                    commitment: body.identity_commitment,
                }),
                signature
            );
            if (recoveredIssuer !== E2E_FIXTURE.issuerAddress) {
                return jsonResponse(route, { detail: 'Fixture issuer mismatch' }, 500);
            }
            return jsonResponse(route, {
                ok: true,
                identity: {
                    recipient: body.wallet_address,
                    identity_root: identityRoot,
                    membership_scope: body.membership_scope,
                    identity_commitment: body.identity_commitment,
                    signature,
                    path_elements: Array(25).fill('0'),
                    path_indices: Array(25).fill('0'),
                },
            });
        }
        if (method === 'GET' && path === '/api/erc4337/config') {
            return jsonResponse(route, {
                enabled: true,
                sponsorship_enabled: true,
                account_type: 'safe',
                bundler_provider: 'pimlico',
                paymaster_provider: 'pimlico',
                paymaster: E2E_FIXTURE.paymaster,
                safe_version: '1.4.1',
                safe_salt_nonce: '0',
                use_multi_send_for_setup: false,
                safe_4337_module_address: E2E_FIXTURE.safe4337Module,
                entry_point: E2E_FIXTURE.entryPoint,
                entry_point_version: '0.7',
                chain_id: String(E2E_FIXTURE.chainId),
                chain_name: 'Sepolia E2E fixture',
            });
        }
        if (method === 'POST' && path === '/api/erc4337/prepare-mint') {
            if (!hasSessionCookie) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            if (!hasCsrfHeader) {
                return jsonResponse(route, { detail: 'Fixture CSRF rejected' }, 403);
            }
            const body = request.postDataJSON();
            state.preparedMintRequests.push(body);
            return jsonResponse(route, {
                ok: true,
                operation_id: 'e2e-fixture-operation-0001',
                user_operation: {
                    ...body.user_operation,
                    callGasLimit: '0x30d40',
                    verificationGasLimit: '0x493e0',
                    preVerificationGas: '0xc350',
                    maxFeePerGas: '0x77359400',
                    maxPriorityFeePerGas: '0x3b9aca00',
                    paymaster: E2E_FIXTURE.paymaster,
                    paymasterData: '0xcafe',
                    paymasterVerificationGasLimit: '0x186a0',
                    paymasterPostOpGasLimit: '0x186a0',
                },
            });
        }
        if (method === 'POST' && path === '/api/erc4337/submit-mint') {
            if (!hasSessionCookie) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            if (!hasCsrfHeader) {
                return jsonResponse(route, { detail: 'Fixture CSRF rejected' }, 403);
            }
            const body = request.postDataJSON();
            state.submittedMintRequests.push(body);
            const operation = deserializeUserOperation(body.user_operation);
            const userOperationHash = getUserOperationHash({
                userOperation: operation,
                entryPointAddress: E2E_FIXTURE.entryPoint,
                entryPointVersion: '0.7',
                chainId: E2E_FIXTURE.chainId,
            });
            return jsonResponse(route, {
                ok: true,
                user_operation_hash: userOperationHash,
                tx_hash: E2E_FIXTURE.txHash,
                token_id: E2E_FIXTURE.tokenId,
            });
        }
        
        if (method === 'GET' && path === '/api/governance/ballot-schema') {
            return jsonResponse(route, {
                types: {
                    EIP712Domain: [
                        { name: 'name', type: 'string' },
                        { name: 'version', type: 'string' },
                        { name: 'chainId', type: 'uint256' }
                    ],
                    Ballot: [
                        { name: 'proposalId', type: 'string' },
                        { name: 'voter', type: 'address' },
                        { name: 'choice', type: 'string' },
                        { name: 'nonce', type: 'string' }
                    ]
                },
                primaryType: 'Ballot',
                domainName: 'DAO Ciudadana',
                domainVersion: '1'
            });
        }
        if (method === 'POST' && path === '/api/governance/vote') {
            if (!hasSessionCookie) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            if (!hasCsrfHeader) {
                return jsonResponse(route, { detail: 'Fixture CSRF rejected' }, 403);
            }
            state.publicVotes = state.publicVotes || [];
            state.publicVotes.push(request.postDataJSON());
            return jsonResponse(route, {
                ok: true,
                message: 'Voto registrado exitosamente'
            });
        }

        if (method === 'GET' && path === '/api/governance/proposals') {
            return jsonResponse(route, [{
                id: E2E_FIXTURE.proposalId,
                title: 'Presupuesto participativo — fixture E2E',
                description: 'Propuesta sintética usada exclusivamente por Playwright.',
                category: 'general',
                status: 'active',
                creator_address: E2E_FIXTURE.userAddress,
                created_at: '2026-08-01T12:00:00.000Z',
                ends_at: '2099-01-01T00:00:00.000Z',
                votes_for: 0,
                votes_against: 0,
                votes_abstain: 0,
                quorum_required: 1,
            }]);
        }
        if (method === 'GET' && path === '/api/maci/status') {
            return jsonResponse(route, {
                key_registry: true,
                private_voting: true,
                coordinator_configured: true,
                tally_proof: true,
                detail: 'Fixture E2E; no representa un despliegue real.',
            });
        }
        if (method === 'POST' && path === '/api/maci/keys') {
            if (!hasSessionCookie) {
                return jsonResponse(route, { detail: 'Fixture session missing' }, 401);
            }
            if (!hasCsrfHeader) {
                return jsonResponse(route, { detail: 'Fixture CSRF rejected' }, 403);
            }
            state.registeredMaciKeys.push({
                authorization: headers.authorization || null,
                cookie: headers.cookie || null,
                csrf: headers['x-csrf-token'] || null,
                body: request.postDataJSON(),
            });
            return jsonResponse(route, { ok: true, state_index: '4' });
        }
        if (
            method === 'GET' &&
            path === `/api/maci/proposals/${E2E_FIXTURE.proposalId}/poll`
        ) {
            return jsonResponse(route, {
                protocol_version: 'maci-v2.5.0',
                proposal_id: E2E_FIXTURE.proposalId,
                poll_id: E2E_FIXTURE.pollId,
                state_index: '4',
                nonce: '1',
                vote_weight: '1',
                vote_options: { for: '0', against: '1', abstain: '2' },
                coordinator_contract: E2E_FIXTURE.maciCoordinator,
                coordinator_public_key: E2E_FIXTURE.coordinatorPublicKey,
                coordinator_key_hash: E2E_FIXTURE.coordinatorKeyHash,
                chain_id: String(E2E_FIXTURE.chainId),
                accepting_messages: true,
                deadline: '2099-01-01T00:00:00.000Z',
            });
        }
        if (
            method === 'POST' &&
            path === `/api/maci/polls/${E2E_FIXTURE.pollId}/messages`
        ) {
            state.encryptedBallots.push({
                authorization: headers.authorization || null,
                cookie: headers.cookie || null,
                csrf: headers['x-csrf-token'] || null,
                body: request.postDataJSON(),
            });
            return jsonResponse(route, {
                ok: true,
                message_id: E2E_FIXTURE.maciMessageId,
            });
        }

        return jsonResponse(
            route,
            { detail: `No E2E fixture registered for ${method} ${path}` },
            501
        );
    });

    return state;
};
