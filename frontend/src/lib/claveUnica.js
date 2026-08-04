const ATTEMPT_VERSION = 1;

export const CLAVE_UNICA_ATTEMPT_KEY =
    'dao-ciudadano:clave-unica:oidc-attempt:v1';

const UNSUPPORTED_OIDC_RESPONSE_PARAMS = Object.freeze([
    'access_token',
    'id_token',
    'refresh_token',
    'token_type',
    'expires_in',
    'scope',
]);

export const CLAVE_UNICA_CALLBACK_PARAMS = Object.freeze([
    'code',
    'state',
    'error',
    'error_description',
    'error_uri',
    'iss',
    'session_state',
    ...UNSUPPORTED_OIDC_RESPONSE_PARAMS,
]);

const MIN_STATE_LENGTH = 32;
const MAX_STATE_LENGTH = 512;
const MAX_CODE_LENGTH = 4096;
const MAX_ERROR_LENGTH = 128;
const MAX_ERROR_DESCRIPTION_LENGTH = 1024;
const MAX_AUTHORIZATION_URL_LENGTH = 8192;
const MAX_ATTEMPT_TTL_SECONDS = 3600;
const MAX_IDENTITY_GRANT_LENGTH = 8192;
const MAX_DISPLAY_NAME_LENGTH = 200;
const STATE_PATTERN = /^[A-Za-z0-9_-]+$/;
const ERROR_PATTERN = /^[A-Za-z0-9_.-]+$/;

export const CLAVE_UNICA_PROTOCOL = Object.freeze({
    protocolVersion: 'clave-unica-oidc-pkce-v1',
    pkceMethod: 'S256',
    redirectTransport: 'frontend-post',
    grantTtlSeconds: 300,
});

export class ClaveUnicaFlowError extends Error {
    constructor(code, message) {
        super(message);
        this.name = 'ClaveUnicaFlowError';
        this.code = code;
    }
}

const fail = (code, message) => {
    throw new ClaveUnicaFlowError(code, message);
};

const isRecord = (value) =>
    Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const validateState = (state) => {
    if (
        typeof state !== 'string' ||
        state.length < MIN_STATE_LENGTH ||
        state.length > MAX_STATE_LENGTH ||
        !STATE_PATTERN.test(state)
    ) {
        fail(
            'OIDC_STATE_INVALID',
            'El intento de ClaveÚnica no contiene un state válido.'
        );
    }
    return state;
};

const validateExpiresIn = (expiresIn) => {
    if (
        !Number.isSafeInteger(expiresIn) ||
        expiresIn <= 0 ||
        expiresIn > MAX_ATTEMPT_TTL_SECONDS
    ) {
        fail(
            'OIDC_TTL_INVALID',
            'La vigencia del intento de ClaveÚnica no es válida.'
        );
    }
    return expiresIn;
};

const resolveNow = (now) => {
    const value = typeof now === 'function' ? now() : now;
    if (!Number.isSafeInteger(value) || value < 0) {
        fail('OIDC_CLOCK_INVALID', 'No se pudo comprobar la vigencia del intento.');
    }
    return value;
};

const resolveStorage = (providedStorage) => {
    if (providedStorage) return providedStorage;
    if (typeof window === 'undefined') {
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'El almacenamiento de sesión no está disponible.'
        );
    }
    try {
        return window.sessionStorage;
    } catch {
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'El almacenamiento de sesión no está disponible.'
        );
    }
};

const requireStorageMethods = (storage) => {
    if (
        !storage ||
        typeof storage.getItem !== 'function' ||
        typeof storage.setItem !== 'function' ||
        typeof storage.removeItem !== 'function'
    ) {
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'El almacenamiento de sesión no está disponible.'
        );
    }
    return storage;
};

const resolveHref = (href) => {
    if (href instanceof URL) return href.toString();
    if (typeof href === 'string' && href) return href;
    if (typeof window !== 'undefined' && window.location?.href) {
        return window.location.href;
    }
    fail('OIDC_URL_INVALID', 'No se pudo leer la URL del flujo ClaveÚnica.');
};

const parseUrl = (href) => {
    const base = typeof window !== 'undefined' && window.location?.origin
        ? window.location.origin
        : 'https://localhost';
    try {
        return new URL(resolveHref(href), base);
    } catch {
        fail('OIDC_URL_INVALID', 'La URL del flujo ClaveÚnica no es válida.');
    }
};

const singleParam = (params, name, { required = false } = {}) => {
    const values = params.getAll(name);
    if (values.length > 1) {
        fail(
            'OIDC_CALLBACK_DUPLICATE_PARAMETER',
            `El callback contiene más de un parámetro ${name}.`
        );
    }
    if (required && values.length !== 1) {
        fail(
            'OIDC_CALLBACK_MISSING_PARAMETER',
            `El callback no contiene el parámetro ${name}.`
        );
    }
    return values[0] ?? null;
};

const fragmentContainsOidcParams = (hash) => {
    if (!hash || hash === '#') return false;
    const raw = hash.slice(1).replace(/^\?/, '');
    if (!raw.includes('=')) return false;
    const params = new URLSearchParams(raw);
    return CLAVE_UNICA_CALLBACK_PARAMS.some((name) => params.has(name));
};

/**
 * Require the backend guarantees that the browser cannot be used as a thin
 * wrapper around a public PKCE oracle. Missing or downgraded capabilities
 * disable the flow; there is deliberately no simulator fallback.
 */
export const validateClaveUnicaStatus = (body) => {
    if (!isRecord(body)) {
        fail('OIDC_STATUS_INVALID', 'El servicio no publicó un estado OIDC válido.');
    }

    const valid =
        body.available === true &&
        body.protocol_version === CLAVE_UNICA_PROTOCOL.protocolVersion &&
        body.pkce_method === CLAVE_UNICA_PROTOCOL.pkceMethod &&
        body.browser_bound === true &&
        body.credential_exchange_browser_bound === true &&
        body.callback_idempotent === true &&
        body.grant_single_use === true &&
        body.redirect_transport === CLAVE_UNICA_PROTOCOL.redirectTransport &&
        body.grant_ttl_seconds === CLAVE_UNICA_PROTOCOL.grantTtlSeconds;

    if (!valid) {
        fail(
            'OIDC_STATUS_UNSAFE',
            'ClaveÚnica no está habilitada con todas las garantías de seguridad requeridas.'
        );
    }

    return {
        available: true,
        protocolVersion: body.protocol_version,
        pkceMethod: body.pkce_method,
        browserBound: true,
        credentialExchangeBrowserBound: true,
        callbackIdempotent: true,
        grantSingleUse: true,
        redirectTransport: body.redirect_transport,
        grantTtlSeconds: body.grant_ttl_seconds,
    };
};

/** Validate the only response allowed to place a civil grant in memory. */
export const validateClaveUnicaCallbackResponse = (
    body,
    expectedGrantTtlSeconds = CLAVE_UNICA_PROTOCOL.grantTtlSeconds
) => {
    if (!isRecord(body) || body.ok !== true) {
        fail('OIDC_CALLBACK_RESPONSE_INVALID', 'ClaveÚnica no confirmó la autenticación.');
    }

    const identityGrant = body.identity_grant;
    if (
        typeof identityGrant !== 'string' ||
        identityGrant.length === 0 ||
        identityGrant.length > MAX_IDENTITY_GRANT_LENGTH ||
        identityGrant !== identityGrant.trim() ||
        /\s|[\u0000-\u001F\u007F]/.test(identityGrant)
    ) {
        fail(
            'OIDC_IDENTITY_GRANT_INVALID',
            'El emisor no devolvió un grant de identidad válido.'
        );
    }
    if (
        !Number.isSafeInteger(expectedGrantTtlSeconds) ||
        body.identity_grant_expires_in !== expectedGrantTtlSeconds
    ) {
        fail(
            'OIDC_IDENTITY_GRANT_TTL_INVALID',
            'La vigencia del grant de identidad no coincide con el contrato publicado.'
        );
    }
    if (body.assurance_level !== 'CLAVE_UNICA') {
        fail(
            'OIDC_ASSURANCE_INVALID',
            'El proveedor no acreditó el nivel ClaveÚnica requerido.'
        );
    }
    if (
        typeof body.name !== 'string' ||
        body.name.length > MAX_DISPLAY_NAME_LENGTH ||
        /[\u0000-\u001F\u007F]/.test(body.name)
    ) {
        fail('OIDC_NAME_INVALID', 'El nombre devuelto por ClaveÚnica no es válido.');
    }

    return {
        identityGrant,
        grantTtlSeconds: body.identity_grant_expires_in,
        assuranceLevel: body.assurance_level,
        name: body.name,
    };
};

/**
 * Validate the exact response emitted by POST /auth/clave-unica/authorize.
 * The state in the JSON body must also be present exactly once in the URL.
 */
export const validateClaveUnicaAuthorization = (body) => {
    if (!isRecord(body)) {
        fail(
            'OIDC_AUTHORIZATION_INVALID',
            'El servicio no devolvió una autorización válida.'
        );
    }

    const authorizationUrl = body.authorization_url;
    if (
        typeof authorizationUrl !== 'string' ||
        authorizationUrl !== authorizationUrl.trim() ||
        authorizationUrl.length === 0 ||
        authorizationUrl.length > MAX_AUTHORIZATION_URL_LENGTH
    ) {
        fail(
            'OIDC_AUTHORIZATION_URL_INVALID',
            'La URL de autorización de ClaveÚnica no es válida.'
        );
    }

    let url;
    try {
        // Authorization must leave the application for an explicit absolute
        // HTTPS origin. Resolving a relative value against our own origin
        // would turn a malformed backend response into a valid redirect.
        url = new URL(authorizationUrl);
    } catch {
        fail(
            'OIDC_AUTHORIZATION_URL_INVALID',
            'La URL de autorización de ClaveÚnica no es absoluta.'
        );
    }
    if (
        url.protocol !== 'https:' ||
        url.username ||
        url.password ||
        url.hash
    ) {
        fail(
            'OIDC_AUTHORIZATION_URL_UNSAFE',
            'La URL de autorización de ClaveÚnica no es segura.'
        );
    }

    const state = validateState(body.state);
    const urlStates = url.searchParams.getAll('state');
    if (urlStates.length !== 1 || urlStates[0] !== state) {
        fail(
            'OIDC_AUTHORIZATION_STATE_MISMATCH',
            'El state de la autorización no coincide con la URL de ClaveÚnica.'
        );
    }

    const expiresIn = validateExpiresIn(body.expires_in);
    return {
        authorizationUrl: url.toString(),
        state,
        expiresIn,
    };
};

/** Store only state + expiry. Codes, grants and identity data never belong here. */
export const storeClaveUnicaAttempt = (
    { state, expiresIn },
    { storage: providedStorage, now = Date.now() } = {}
) => {
    const normalizedState = validateState(state);
    const normalizedTtl = validateExpiresIn(expiresIn);
    const nowMs = resolveNow(now);
    const expiresAt = nowMs + normalizedTtl * 1000;
    if (!Number.isSafeInteger(expiresAt)) {
        fail('OIDC_TTL_INVALID', 'La vigencia del intento de ClaveÚnica no es válida.');
    }

    const storage = requireStorageMethods(resolveStorage(providedStorage));
    const serialized = JSON.stringify({
        version: ATTEMPT_VERSION,
        state: normalizedState,
        expiresAt,
    });
    try {
        storage.setItem(CLAVE_UNICA_ATTEMPT_KEY, serialized);
        if (storage.getItem(CLAVE_UNICA_ATTEMPT_KEY) !== serialized) {
            throw new Error('sessionStorage did not retain the OIDC attempt');
        }
    } catch {
        try {
            storage.removeItem(CLAVE_UNICA_ATTEMPT_KEY);
        } catch {
            // The caller still fails closed below. The record has its own TTL.
        }
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'No se pudo conservar el intento de ClaveÚnica en esta pestaña.'
        );
    }

    return { state: normalizedState, expiresAt };
};

/**
 * Read and remove the browser-bound attempt before returning it. Any malformed,
 * expired or mismatched record is consumed as well, preventing silent reuse.
 */
export const consumeClaveUnicaAttempt = (
    callbackState,
    { storage: providedStorage, now = Date.now() } = {}
) => {
    const normalizedCallbackState = validateState(callbackState);
    const storage = requireStorageMethods(resolveStorage(providedStorage));
    let raw;
    try {
        raw = storage.getItem(CLAVE_UNICA_ATTEMPT_KEY);
        storage.removeItem(CLAVE_UNICA_ATTEMPT_KEY);
    } catch {
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'No se pudo consumir el intento de ClaveÚnica en esta pestaña.'
        );
    }

    if (!raw) {
        fail(
            'OIDC_ATTEMPT_MISSING',
            'No existe un intento de ClaveÚnica pendiente en esta pestaña.'
        );
    }

    let attempt;
    try {
        attempt = JSON.parse(raw);
    } catch {
        fail('OIDC_ATTEMPT_INVALID', 'El intento de ClaveÚnica guardado no es válido.');
    }
    if (
        !isRecord(attempt) ||
        attempt.version !== ATTEMPT_VERSION ||
        !Number.isSafeInteger(attempt.expiresAt)
    ) {
        fail('OIDC_ATTEMPT_INVALID', 'El intento de ClaveÚnica guardado no es válido.');
    }

    const storedState = validateState(attempt.state);
    if (storedState !== normalizedCallbackState) {
        fail(
            'OIDC_CALLBACK_STATE_MISMATCH',
            'El callback no corresponde al intento iniciado en esta pestaña.'
        );
    }
    if (attempt.expiresAt <= resolveNow(now)) {
        fail(
            'OIDC_ATTEMPT_EXPIRED',
            'El intento de ClaveÚnica expiró. Vuelve a comenzar.'
        );
    }

    return { state: storedState, expiresAt: attempt.expiresAt };
};

export const clearClaveUnicaAttempt = ({ storage: providedStorage } = {}) => {
    const storage = requireStorageMethods(resolveStorage(providedStorage));
    try {
        storage.removeItem(CLAVE_UNICA_ATTEMPT_KEY);
    } catch {
        fail(
            'OIDC_STORAGE_UNAVAILABLE',
            'No se pudo limpiar el intento de ClaveÚnica.'
        );
    }
};

/** Parse an authorization-code callback without accepting ambiguous shapes. */
export const parseClaveUnicaCallback = (href) => {
    const url = parseUrl(href);
    if (fragmentContainsOidcParams(url.hash)) {
        fail(
            'OIDC_CALLBACK_FRAGMENT_UNSUPPORTED',
            'ClaveÚnica devolvió parámetros en un formato no admitido.'
        );
    }

    const params = url.searchParams;
    if (UNSUPPORTED_OIDC_RESPONSE_PARAMS.some((name) => params.has(name))) {
        fail(
            'OIDC_CALLBACK_RESPONSE_MODE_UNSUPPORTED',
            'ClaveÚnica devolvió tokens en un canal de respuesta no admitido.'
        );
    }
    const state = validateState(singleParam(params, 'state', { required: true }));
    const code = singleParam(params, 'code');
    const providerError = singleParam(params, 'error');
    const errorDescription = singleParam(params, 'error_description');
    const errorUri = singleParam(params, 'error_uri');

    if (code && providerError) {
        fail(
            'OIDC_CALLBACK_AMBIGUOUS',
            'El callback de ClaveÚnica contiene éxito y error a la vez.'
        );
    }

    if (providerError) {
        if (
            providerError.length > MAX_ERROR_LENGTH ||
            !ERROR_PATTERN.test(providerError)
        ) {
            fail(
                'OIDC_PROVIDER_ERROR_INVALID',
                'ClaveÚnica devolvió un código de error no válido.'
            );
        }
        if (
            errorDescription &&
            errorDescription.length > MAX_ERROR_DESCRIPTION_LENGTH
        ) {
            fail(
                'OIDC_PROVIDER_ERROR_INVALID',
                'ClaveÚnica devolvió un error demasiado extenso.'
            );
        }
        if (errorUri && errorUri.length > MAX_AUTHORIZATION_URL_LENGTH) {
            fail(
                'OIDC_PROVIDER_ERROR_INVALID',
                'ClaveÚnica devolvió una referencia de error no válida.'
            );
        }
        return { kind: 'error', state, error: providerError };
    }

    if (errorDescription || errorUri) {
        fail(
            'OIDC_CALLBACK_AMBIGUOUS',
            'El callback contiene metadatos de error sin un error.'
        );
    }
    if (
        typeof code !== 'string' ||
        code.length === 0 ||
        code.length > MAX_CODE_LENGTH ||
        /\s|[\u0000-\u001F\u007F]/.test(code)
    ) {
        fail(
            'OIDC_CALLBACK_CODE_INVALID',
            'El callback no contiene un código de autorización válido.'
        );
    }

    return { kind: 'success', code, state };
};

const cleanHash = (hash) => {
    if (!fragmentContainsOidcParams(hash)) return hash;
    const hadQuestionMark = hash.startsWith('#?');
    const params = new URLSearchParams(hash.slice(1).replace(/^\?/, ''));
    CLAVE_UNICA_CALLBACK_PARAMS.forEach((name) => params.delete(name));
    const remaining = params.toString();
    return remaining ? `#${hadQuestionMark ? '?' : ''}${remaining}` : '';
};

/** Return a same-origin relative URL with only OIDC callback fields removed. */
export const cleanClaveUnicaCallbackUrl = (href) => {
    const url = parseUrl(href);
    CLAVE_UNICA_CALLBACK_PARAMS.forEach((name) => url.searchParams.delete(name));
    url.hash = cleanHash(url.hash);
    return `${url.pathname}${url.search}${url.hash}`;
};

/**
 * Capture the current URL, remove callback secrets from the address bar first,
 * and only then parse them. Cleanup therefore also happens on malformed input.
 */
export const readAndCleanClaveUnicaCallback = ({
    href,
    replace,
} = {}) => {
    const originalHref = resolveHref(href);
    const cleanUrl = cleanClaveUnicaCallbackUrl(originalHref);
    const replaceUrl = replace || ((nextUrl) => {
        if (typeof window === 'undefined' || !window.history?.replaceState) {
            fail('OIDC_HISTORY_UNAVAILABLE', 'No se pudo limpiar la URL del callback.');
        }
        window.history.replaceState(window.history.state, '', nextUrl);
    });
    if (typeof replaceUrl !== 'function') {
        fail('OIDC_HISTORY_UNAVAILABLE', 'No se pudo limpiar la URL del callback.');
    }
    try {
        replaceUrl(cleanUrl);
    } catch (error) {
        if (error instanceof ClaveUnicaFlowError) throw error;
        fail('OIDC_HISTORY_UNAVAILABLE', 'No se pudo limpiar la URL del callback.');
    }
    return parseClaveUnicaCallback(originalHref);
};

/**
 * Validate, persist the state, then navigate. A redirect can never start if
 * sessionStorage is unavailable, because its callback could not be bound.
 */
export const redirectToClaveUnica = (
    body,
    {
        storage,
        now = Date.now(),
        navigate,
    } = {}
) => {
    const authorization = validateClaveUnicaAuthorization(body);
    const attempt = storeClaveUnicaAttempt(
        {
            state: authorization.state,
            expiresIn: authorization.expiresIn,
        },
        { storage, now }
    );
    const navigateTo = navigate || ((url) => {
        if (typeof window === 'undefined' || !window.location?.assign) {
            fail('OIDC_NAVIGATION_UNAVAILABLE', 'No se pudo abrir ClaveÚnica.');
        }
        window.location.assign(url);
    });
    if (typeof navigateTo !== 'function') {
        clearClaveUnicaAttempt({ storage });
        fail('OIDC_NAVIGATION_UNAVAILABLE', 'No se pudo abrir ClaveÚnica.');
    }
    try {
        navigateTo(authorization.authorizationUrl);
    } catch (error) {
        try {
            clearClaveUnicaAttempt({ storage });
        } catch {
            // The short TTL remains the final guard if cleanup is unavailable.
        }
        if (error instanceof ClaveUnicaFlowError) throw error;
        fail('OIDC_NAVIGATION_FAILED', 'No se pudo abrir ClaveÚnica.');
    }
    return attempt;
};
