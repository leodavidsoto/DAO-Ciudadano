/**
 * Security Utilities
 * Frontend security helpers for signing, validation, and secure storage
 */

// === Address Validation ===

/**
 * Validate Ethereum address format
 */
export const isValidEthAddress = (address) => {
    if (!address || typeof address !== 'string') return false;
    return /^0x[a-fA-F0-9]{40}$/.test(address);
};

/**
 * Validate checksum address (EIP-55)
 */
export const isChecksumAddress = (address) => {
    if (!isValidEthAddress(address)) return false;
    // Basic checksum validation
    const hasUppercase = /[A-F]/.test(address.slice(2));
    const hasLowercase = /[a-f]/.test(address.slice(2));
    return hasUppercase || hasLowercase;
};

// === Nonce Generation ===

/**
 * Generate a cryptographically secure nonce
 */
export const generateNonce = () => {
    const array = new Uint8Array(32);
    crypto.getRandomValues(array);
    return Array.from(array, byte => byte.toString(16).padStart(2, '0')).join('');
};

/**
 * Generate a timestamp-based nonce (for vote ordering)
 */
export const generateTimestampNonce = () => {
    const timestamp = Date.now().toString(16);
    const random = generateNonce().slice(0, 16);
    return `${timestamp}-${random}`;
};

// === Message Signing ===

/**
 * Create a signable message for votes
 */
export const createVoteMessage = (proposalId, vote, nonce) => {
    return JSON.stringify({
        action: 'vote',
        proposalId,
        vote,
        nonce,
        timestamp: Date.now()
    });
};

/**
 * Create a signable message for delegation
 */
export const createDelegationMessage = (delegateAddress, nonce) => {
    return JSON.stringify({
        action: 'delegate',
        delegate: delegateAddress.toLowerCase(),
        nonce,
        timestamp: Date.now()
    });
};

/**
 * Sign a message with the connected wallet
 */
export const signMessage = async (signer, message) => {
    if (!signer) {
        throw new Error('Wallet not connected');
    }

    try {
        const signature = await signer.signMessage(message);
        return signature;
    } catch (error) {
        if (error.code === 4001) {
            throw new Error('Signature rejected by user');
        }
        throw error;
    }
};

// === Secure Storage ===

const STORAGE_PREFIX = 'dao_ciudadana_';

/**
 * Store data securely with expiration
 */
export const secureStore = (key, value, expiresInMs = null) => {
    const data = {
        value,
        timestamp: Date.now(),
        expires: expiresInMs ? Date.now() + expiresInMs : null
    };

    try {
        localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(data));
        return true;
    } catch (error) {
        console.error('Secure storage error:', error);
        return false;
    }
};

/**
 * Retrieve data from secure storage
 */
export const secureRetrieve = (key) => {
    try {
        const item = localStorage.getItem(STORAGE_PREFIX + key);
        if (!item) return null;

        const data = JSON.parse(item);

        // Check expiration
        if (data.expires && Date.now() > data.expires) {
            localStorage.removeItem(STORAGE_PREFIX + key);
            return null;
        }

        return data.value;
    } catch (error) {
        console.error('Secure retrieve error:', error);
        return null;
    }
};

/**
 * Remove data from secure storage
 */
export const secureRemove = (key) => {
    localStorage.removeItem(STORAGE_PREFIX + key);
};

/**
 * Clear all DAO-related storage
 */
export const secureClearAll = () => {
    const keysToRemove = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith(STORAGE_PREFIX)) {
            keysToRemove.push(key);
        }
    }
    keysToRemove.forEach(key => localStorage.removeItem(key));
};

// === Input Sanitization ===

/**
 * Sanitize user input (remove potential XSS)
 */
export const sanitizeInput = (input) => {
    if (typeof input !== 'string') return input;

    return input
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#x27;')
        .replace(/\//g, '&#x2F;')
        .trim();
};

/**
 * Validate proposal title
 */
export const validateProposalTitle = (title) => {
    if (!title || typeof title !== 'string') {
        return { valid: false, error: 'Title is required' };
    }

    const sanitized = sanitizeInput(title);

    if (sanitized.length < 5) {
        return { valid: false, error: 'Title must be at least 5 characters' };
    }

    if (sanitized.length > 100) {
        return { valid: false, error: 'Title must be less than 100 characters' };
    }

    return { valid: true, sanitized };
};

/**
 * Validate proposal description
 */
export const validateProposalDescription = (description) => {
    if (!description || typeof description !== 'string') {
        return { valid: false, error: 'Description is required' };
    }

    const sanitized = sanitizeInput(description);

    if (sanitized.length < 20) {
        return { valid: false, error: 'Description must be at least 20 characters' };
    }

    if (sanitized.length > 5000) {
        return { valid: false, error: 'Description must be less than 5000 characters' };
    }

    return { valid: true, sanitized };
};

// === Rate Limiting (Client-Side) ===

const rateLimits = new Map();

/**
 * Client-side rate limiting for sensitive actions
 */
export const checkRateLimit = (action, maxAttempts = 5, windowMs = 60000) => {
    const key = action;
    const now = Date.now();

    if (!rateLimits.has(key)) {
        rateLimits.set(key, []);
    }

    const attempts = rateLimits.get(key);

    // Remove old attempts
    const recentAttempts = attempts.filter(t => now - t < windowMs);
    rateLimits.set(key, recentAttempts);

    if (recentAttempts.length >= maxAttempts) {
        const oldestAttempt = Math.min(...recentAttempts);
        const retryAfter = Math.ceil((oldestAttempt + windowMs - now) / 1000);
        return {
            allowed: false,
            error: `Too many attempts. Please wait ${retryAfter} seconds.`
        };
    }

    // Record this attempt
    recentAttempts.push(now);
    rateLimits.set(key, recentAttempts);

    return { allowed: true };
};
