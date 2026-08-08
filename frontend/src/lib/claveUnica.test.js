import {
    CLAVE_UNICA_ATTEMPT_KEY,
    ClaveUnicaFlowError,
    cleanClaveUnicaCallbackUrl,
    consumeClaveUnicaAttempt,
    parseClaveUnicaCallback,
    readAndCleanClaveUnicaCallback,
    redirectToClaveUnica,
    storeClaveUnicaAttempt,
    validateClaveUnicaAuthorization,
    validateClaveUnicaCallbackResponse,
    validateClaveUnicaStatus,
} from './claveUnica';

const STATE = 'state_1234567890abcdefghijklmnopqrstuvwxyz';
const OTHER_STATE = 'state_abcdefghijklmnopqrstuvwxyz1234567890';
const NOW = 1_800_000_000_000;

const authorization = (overrides = {}) => ({
    authorization_url:
        `https://accounts.example.gob.cl/authorize?client_id=dao&state=${STATE}`,
    state: STATE,
    expires_in: 600,
    ...overrides,
});

const secureStatus = (overrides = {}) => ({
    available: true,
    protocol_version: 'clave-unica-oidc-pkce-v1',
    pkce_method: 'S256',
    browser_bound: true,
    credential_exchange_browser_bound: true,
    callback_idempotent: true,
    grant_single_use: true,
    redirect_transport: 'frontend-post',
    grant_ttl_seconds: 300,
    ...overrides,
});

const callbackResponse = (overrides = {}) => ({
    ok: true,
    identity_grant: 'opaque-one-time-identity-grant-123456',
    identity_grant_expires_in: 300,
    assurance_level: 'CLAVE_UNICA',
    name: 'Ciudadana',
    ...overrides,
});

beforeEach(() => {
    window.sessionStorage.clear();
    window.history.replaceState({}, '', '/unete');
});

test('enables OIDC only for the exact fail-closed capability contract', () => {
    expect(validateClaveUnicaStatus(secureStatus())).toEqual({
        available: true,
        protocolVersion: 'clave-unica-oidc-pkce-v1',
        pkceMethod: 'S256',
        browserBound: true,
        credentialExchangeBrowserBound: true,
        callbackIdempotent: true,
        grantSingleUse: true,
        redirectTransport: 'frontend-post',
        grantTtlSeconds: 300,
    });

    [
        ['available', false],
        ['protocol_version', 'legacy'],
        ['pkce_method', 'plain'],
        ['browser_bound', false],
        ['credential_exchange_browser_bound', false],
        ['callback_idempotent', false],
        ['grant_single_use', false],
        ['redirect_transport', 'query-grant'],
        ['grant_ttl_seconds', 600],
    ].forEach(([field, value]) => {
        expect(() => validateClaveUnicaStatus(secureStatus({ [field]: value })))
            .toThrow(expect.objectContaining({ code: 'OIDC_STATUS_UNSAFE' }));
    });
});

test('accepts only a bounded ClaveÚnica grant matching the published contract', () => {
    expect(validateClaveUnicaCallbackResponse(callbackResponse())).toEqual({
        identityGrant: 'opaque-one-time-identity-grant-123456',
        grantTtlSeconds: 300,
        assuranceLevel: 'CLAVE_UNICA',
        name: 'Ciudadana',
    });

    expect(() => validateClaveUnicaCallbackResponse(callbackResponse({
        identity_grant: ' grant-with-whitespace ',
    }))).toThrow(expect.objectContaining({ code: 'OIDC_IDENTITY_GRANT_INVALID' }));
    expect(() => validateClaveUnicaCallbackResponse(callbackResponse({
        identity_grant_expires_in: 301,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_IDENTITY_GRANT_TTL_INVALID' }));
    expect(() => validateClaveUnicaCallbackResponse(callbackResponse({
        assurance_level: 'DEMO',
    }))).toThrow(expect.objectContaining({ code: 'OIDC_ASSURANCE_INVALID' }));
});

test('accepts only an HTTPS authorization URL carrying the exact state once', () => {
    expect(validateClaveUnicaAuthorization(authorization())).toEqual({
        authorizationUrl:
            `https://accounts.example.gob.cl/authorize?client_id=dao&state=${STATE}`,
        state: STATE,
        expiresIn: 600,
    });

    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url:
            `http://accounts.example.gob.cl/authorize?state=${STATE}`,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_AUTHORIZATION_URL_UNSAFE' }));

    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url: `/authorize?state=${STATE}`,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_AUTHORIZATION_URL_INVALID' }));

    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url: `//accounts.example.gob.cl/authorize?state=${STATE}`,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_AUTHORIZATION_URL_INVALID' }));

    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url:
            `https://accounts.example.gob.cl/authorize?state=${OTHER_STATE}`,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_AUTHORIZATION_STATE_MISMATCH' }));

    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url:
            `https://accounts.example.gob.cl/authorize?state=${STATE}&state=${STATE}`,
    }))).toThrow(expect.objectContaining({ code: 'OIDC_AUTHORIZATION_STATE_MISMATCH' }));
});

test('rejects credentials, fragments, malformed state and unsafe TTLs', () => {
    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url:
            `https://user:pass@accounts.example.gob.cl/authorize?state=${STATE}`,
    }))).toThrow(ClaveUnicaFlowError);
    expect(() => validateClaveUnicaAuthorization(authorization({
        authorization_url:
            `https://accounts.example.gob.cl/authorize?state=${STATE}#fragment`,
    }))).toThrow(ClaveUnicaFlowError);
    expect(() => validateClaveUnicaAuthorization(authorization({ state: 'short' })))
        .toThrow(expect.objectContaining({ code: 'OIDC_STATE_INVALID' }));
    expect(() => validateClaveUnicaAuthorization(authorization({ expires_in: 0 })))
        .toThrow(expect.objectContaining({ code: 'OIDC_TTL_INVALID' }));
    expect(() => validateClaveUnicaAuthorization(authorization({ expires_in: 3601 })))
        .toThrow(expect.objectContaining({ code: 'OIDC_TTL_INVALID' }));
});

test('stores only state and expiry in sessionStorage', () => {
    const attempt = storeClaveUnicaAttempt(
        { state: STATE, expiresIn: 600 },
        { now: NOW }
    );
    const stored = JSON.parse(
        window.sessionStorage.getItem(CLAVE_UNICA_ATTEMPT_KEY)
    );

    expect(attempt).toEqual({ state: STATE, expiresAt: NOW + 600_000 });
    expect(stored).toEqual({
        version: 1,
        state: STATE,
        expiresAt: NOW + 600_000,
    });
    expect(JSON.stringify(stored)).not.toMatch(/code|grant|authorization_url/i);
});

test('consumes a matching unexpired attempt exactly once', () => {
    storeClaveUnicaAttempt({ state: STATE, expiresIn: 60 }, { now: NOW });

    expect(consumeClaveUnicaAttempt(STATE, { now: NOW + 59_999 })).toEqual({
        state: STATE,
        expiresAt: NOW + 60_000,
    });
    expect(window.sessionStorage.getItem(CLAVE_UNICA_ATTEMPT_KEY)).toBeNull();
    expect(() => consumeClaveUnicaAttempt(STATE, { now: NOW + 59_999 }))
        .toThrow(expect.objectContaining({ code: 'OIDC_ATTEMPT_MISSING' }));
});

test('mismatched, expired and malformed attempts are removed fail-closed', () => {
    storeClaveUnicaAttempt({ state: STATE, expiresIn: 60 }, { now: NOW });
    expect(() => consumeClaveUnicaAttempt(OTHER_STATE, { now: NOW + 1 }))
        .toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_STATE_MISMATCH' }));
    expect(window.sessionStorage.getItem(CLAVE_UNICA_ATTEMPT_KEY)).toBeNull();

    storeClaveUnicaAttempt({ state: STATE, expiresIn: 60 }, { now: NOW });
    expect(() => consumeClaveUnicaAttempt(STATE, { now: NOW + 60_000 }))
        .toThrow(expect.objectContaining({ code: 'OIDC_ATTEMPT_EXPIRED' }));
    expect(window.sessionStorage.getItem(CLAVE_UNICA_ATTEMPT_KEY)).toBeNull();

    window.sessionStorage.setItem(CLAVE_UNICA_ATTEMPT_KEY, '{broken');
    expect(() => consumeClaveUnicaAttempt(STATE, { now: NOW }))
        .toThrow(expect.objectContaining({ code: 'OIDC_ATTEMPT_INVALID' }));
    expect(window.sessionStorage.getItem(CLAVE_UNICA_ATTEMPT_KEY)).toBeNull();
});

test('never redirects when sessionStorage cannot retain the attempt', () => {
    const navigate = jest.fn();
    const storage = {
        getItem: jest.fn(() => null),
        setItem: jest.fn(() => { throw new Error('blocked'); }),
        removeItem: jest.fn(),
    };

    expect(() => redirectToClaveUnica(authorization(), {
        storage,
        now: NOW,
        navigate,
    })).toThrow(expect.objectContaining({ code: 'OIDC_STORAGE_UNAVAILABLE' }));
    expect(navigate).not.toHaveBeenCalled();
});

test('redirect wrapper validates, stores, then navigates and clears on failure', () => {
    const events = [];
    const storage = {
        value: null,
        setItem(key, value) {
            events.push('store');
            this.value = value;
        },
        getItem() { return this.value; },
        removeItem() {
            events.push('clear');
            this.value = null;
        },
    };
    const navigate = jest.fn(() => events.push('navigate'));

    redirectToClaveUnica(authorization(), { storage, now: NOW, navigate });
    expect(events).toEqual(['store', 'navigate']);

    expect(() => redirectToClaveUnica(authorization(), {
        storage,
        now: NOW,
        navigate: () => { throw new Error('navigation blocked'); },
    })).toThrow(expect.objectContaining({ code: 'OIDC_NAVIGATION_FAILED' }));
    expect(storage.value).toBeNull();
    expect(events.at(-1)).toBe('clear');
});

test('parses one bounded success callback or one provider error', () => {
    expect(parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?code=code-123&state=${STATE}`
    )).toEqual({ kind: 'success', code: 'code-123', state: STATE });

    expect(parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?error=access_denied&state=${STATE}`
    )).toEqual({ kind: 'error', error: 'access_denied', state: STATE });
});

test('rejects missing, duplicate, mixed or oversized callback parameters', () => {
    expect(() => parseClaveUnicaCallback(
        'https://estamosdao.cl/unete/callback?code=x'
    )).toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_MISSING_PARAMETER' }));

    expect(() => parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?code=a&code=b&state=${STATE}`
    )).toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_DUPLICATE_PARAMETER' }));

    expect(() => parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?code=a&error=access_denied&state=${STATE}`
    )).toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_AMBIGUOUS' }));

    const oversizedCode = 'a'.repeat(4097);
    expect(() => parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?code=${oversizedCode}&state=${STATE}`
    )).toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_CODE_INVALID' }));

    expect(() => parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?error=${'a'.repeat(129)}&state=${STATE}`
    )).toThrow(expect.objectContaining({ code: 'OIDC_PROVIDER_ERROR_INVALID' }));

    expect(() => parseClaveUnicaCallback(
        `https://estamosdao.cl/unete/callback?code=a&state=${STATE}&id_token=secret`
    )).toThrow(expect.objectContaining({
        code: 'OIDC_CALLBACK_RESPONSE_MODE_UNSUPPORTED',
    }));
});

test('removes OIDC parameters while preserving unrelated query and hash data', () => {
    const cleaned = cleanClaveUnicaCallbackUrl(
        `https://estamosdao.cl/unete/callback?returnTo=wallet&code=secret&state=${STATE}` +
        '&theme=civic&id_token=query-secret#error=access_denied&access_token=fragment-secret&panel=identity'
    );

    expect(cleaned).toBe(
        '/unete/callback?returnTo=wallet&theme=civic#panel=identity'
    );
});

test('cleans the address bar before parsing, including malformed callbacks', () => {
    const events = [];
    const replace = jest.fn((url) => events.push(['replace', url]));

    const parsed = readAndCleanClaveUnicaCallback({
        href:
            `https://estamosdao.cl/unete/callback?code=code-123&state=${STATE}&keep=1`,
        replace,
    });
    events.push(['parsed', parsed.kind]);

    expect(events).toEqual([
        ['replace', '/unete/callback?keep=1'],
        ['parsed', 'success'],
    ]);

    expect(() => readAndCleanClaveUnicaCallback({
        href: `https://estamosdao.cl/unete/callback?code=a&code=b&state=${STATE}&keep=1`,
        replace,
    })).toThrow(expect.objectContaining({ code: 'OIDC_CALLBACK_DUPLICATE_PARAMETER' }));
    expect(replace).toHaveBeenLastCalledWith('/unete/callback?keep=1');
});
