const CSRF_ONE = 'a'.repeat(64);
const CSRF_TWO = 'b'.repeat(64);

const makeClient = () => ({
    interceptors: {
        request: { use: jest.fn() },
        response: { use: jest.fn() },
    },
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
});

const loadApi = () => {
    jest.resetModules();
    const credentialed = makeClient();
    const anonymous = makeClient();
    const create = jest.fn()
        .mockReturnValueOnce(credentialed)
        .mockReturnValueOnce(anonymous);

    jest.doMock('axios', () => ({
        __esModule: true,
        default: { create },
    }));

    let api;
    let session;
    jest.isolateModules(() => {
        api = require('./api');
        session = require('./session');
    });

    return {
        api,
        session,
        create,
        credentialed,
        anonymous,
        requestInterceptor: credentialed.interceptors.request.use.mock.calls[0][0],
        responseInterceptor: credentialed.interceptors.response.use.mock.calls[0][0],
        responseErrorInterceptor: credentialed.interceptors.response.use.mock.calls[0][1],
    };
};

afterEach(() => {
    jest.dontMock('axios');
    jest.restoreAllMocks();
    window.localStorage.clear();
});

test('uses cookies for authenticated calls and keeps MACI credentialless', () => {
    const { create, anonymous } = loadApi();

    expect(create).toHaveBeenNthCalledWith(1, expect.objectContaining({
        withCredentials: true,
        withXSRFToken: false,
    }));
    expect(create).toHaveBeenNthCalledWith(2, expect.objectContaining({
        withCredentials: false,
        withXSRFToken: false,
    }));
    expect(anonymous.interceptors.request.use).not.toHaveBeenCalled();
    expect(anonymous.interceptors.response.use).not.toHaveBeenCalled();
});

test('purges legacy JWT storage without reading or writing session values', async () => {
    window.localStorage.setItem('auth_token', 'legacy.jwt');
    window.localStorage.setItem('auth_address', '0xlegacy');
    window.localStorage.setItem('zk_identity_secret_v2', 'keep-this-secret');
    const getItem = jest.spyOn(Storage.prototype, 'getItem');
    const setItem = jest.spyOn(Storage.prototype, 'setItem');

    const { api, credentialed } = loadApi();
    credentialed.get.mockResolvedValue({ data: { address: '0x1', csrf_token: CSRF_ONE } });
    await api.walletAPI.session();

    expect(getItem).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    getItem.mockRestore();
    setItem.mockRestore();
    expect(window.localStorage.getItem('auth_token')).toBeNull();
    expect(window.localStorage.getItem('auth_address')).toBeNull();
    expect(window.localStorage.getItem('zk_identity_secret_v2')).toBe('keep-this-secret');
});

test('requests cookie-only SIWE and attaches the in-memory CSRF token to mutations', async () => {
    const {
        api,
        credentialed,
        requestInterceptor,
        responseInterceptor,
    } = loadApi();
    credentialed.post.mockResolvedValue({ data: {} });

    await api.walletAPI.verify('0xabc', 'nonce-1', '0xsig');
    expect(credentialed.post).toHaveBeenCalledWith('/wallet/verify', {
        address: '0xabc',
        nonce: 'nonce-1',
        signature: '0xsig',
        session_transport: 'cookie',
    });

    responseInterceptor({ data: { csrf_token: CSRF_ONE }, headers: {} });
    const postConfig = {
        method: 'post',
        headers: { Authorization: 'Bearer legacy' },
    };
    requestInterceptor(postConfig);
    expect(postConfig.headers).toEqual({ 'X-CSRF-Token': CSRF_ONE });

    const getConfig = { method: 'get', headers: {} };
    requestInterceptor(getConfig);
    expect(getConfig.headers).not.toHaveProperty('X-CSRF-Token');

    responseInterceptor({ data: { csrf_token: CSRF_TWO }, headers: {} });
    const deleteConfig = { method: 'delete', headers: {} };
    requestInterceptor(deleteConfig);
    expect(deleteConfig.headers['X-CSRF-Token']).toBe(CSRF_TWO);
});

test('invalidates CSRF and React subscribers on 401 without retrying', async () => {
    const {
        session,
        requestInterceptor,
        responseInterceptor,
        responseErrorInterceptor,
    } = loadApi();
    responseInterceptor({ data: { csrf_token: CSRF_ONE }, headers: {} });
    const listener = jest.fn();
    const unsubscribe = session.subscribeSessionInvalidation(listener);
    const unauthorized = { response: { status: 401 } };

    await expect(responseErrorInterceptor(unauthorized)).rejects.toBe(unauthorized);
    expect(listener).toHaveBeenCalledWith('unauthorized');

    const nextMutation = { method: 'put', headers: {} };
    requestInterceptor(nextMutation);
    expect(nextMutation.headers).not.toHaveProperty('X-CSRF-Token');
    unsubscribe();
});

test('exposes session and logout endpoints and submits MACI on the anonymous client', async () => {
    const { api, credentialed, anonymous } = loadApi();
    credentialed.get.mockResolvedValue({ data: {} });
    credentialed.post.mockResolvedValue({ data: {} });
    anonymous.post.mockResolvedValue({ data: {} });

    await api.walletAPI.session();
    await api.walletAPI.logout();
    expect(credentialed.get).toHaveBeenCalledWith('/wallet/session');
    expect(credentialed.post).toHaveBeenCalledWith('/wallet/logout');

    const ballot = {
        protocolVersion: 'maci-v2.5.0',
        proposalId: 'proposal-1',
        pollId: '7',
        message: { data: Array.from({ length: 10 }, (_, index) => String(index + 1)) },
        encryptionPublicKey: { x: '11', y: '12' },
        coordinatorKeyHash: `0x${'ab'.repeat(32)}`,
        idempotencyKey: '12345678-1234-4234-9234-123456789abc',
    };
    await api.maciAPI.submitEncryptedBallot(ballot);

    expect(anonymous.post).toHaveBeenCalledWith(
        '/maci/polls/7/messages',
        expect.objectContaining({ proposal_id: 'proposal-1', poll_id: '7' })
    );
});
