/** Minimal Node `crypto.randomBytes` compatibility for MACI 2.5 in browsers. */
import { Buffer } from 'buffer';

export const randomBytes = (size) => {
    if (!Number.isSafeInteger(size) || size <= 0 || size > 65536) {
        throw new TypeError('randomBytes requiere un tamaño seguro.');
    }
    if (!globalThis.crypto?.getRandomValues) {
        throw new Error('Este navegador no ofrece un generador criptográfico seguro.');
    }
    const bytes = new Uint8Array(size);
    globalThis.crypto.getRandomValues(bytes);
    return Buffer.from(bytes);
};

const browserCrypto = { randomBytes };

export default browserCrypto;
