/**
 * Browser-only session metadata.
 *
 * The SIWE JWT is intentionally absent from this module: the browser keeps it
 * in an HttpOnly cookie. Only the non-authenticating CSRF value is held in
 * memory, so a reload must restore it through GET /wallet/session.
 */

export const LEGACY_SESSION_STORAGE_KEYS = Object.freeze([
    'auth_token',
    'auth_address',
]);

let csrfToken = null;
const invalidationListeners = new Set();

export const clearLegacySessionStorage = () => {
    if (typeof window === 'undefined') return;
    let storage;
    try {
        storage = window.localStorage;
    } catch {
        return;
    }
    if (!storage) return;

    for (const key of LEGACY_SESSION_STORAGE_KEYS) {
        try {
            storage.removeItem(key);
        } catch {
            // Storage can be disabled by browser privacy settings. The app does
            // not need storage access to establish a cookie-backed session.
        }
    }
};

export const isValidCsrfToken = (value) =>
    typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value);

export const setCsrfToken = (value) => {
    csrfToken = isValidCsrfToken(value) ? value : null;
    return csrfToken;
};

export const getCsrfToken = () => {
    if (typeof document !== 'undefined') {
        const match = document.cookie.match(/dao_csrf=([^;]+)/);
        if (match && isValidCsrfToken(match[1])) {
            return match[1];
        }
    }
    return csrfToken;
};

export const clearCsrfToken = () => {
    csrfToken = null;
};

export const subscribeSessionInvalidation = (listener) => {
    if (typeof listener !== 'function') {
        throw new TypeError('Session invalidation listener must be a function.');
    }
    invalidationListeners.add(listener);
    return () => invalidationListeners.delete(listener);
};

export const invalidateSession = (reason = 'invalid') => {
    clearCsrfToken();
    for (const listener of invalidationListeners) {
        try {
            listener(reason);
        } catch {
            // One consumer must not prevent the remaining session state from
            // being invalidated.
        }
    }
};

// Remove any JWT left by a previous frontend version as soon as this module is
// evaluated. No current code reads or writes these keys afterward.
clearLegacySessionStorage();
