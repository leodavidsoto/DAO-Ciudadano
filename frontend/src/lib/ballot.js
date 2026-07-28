/**
 * Signed ballots (EIP-712).
 *
 * A signed ballot is what lets anyone recompute the result without trusting
 * the server: they recover each signer from the stored signature and count.
 * Without it, the tally is only as trustworthy as whoever runs the backend.
 *
 * The domain and types come from the backend, never from a local copy: a
 * hand-maintained signing schema drifts, and when it does every signature
 * fails to verify with no obvious cause.
 */
import { governanceAPI } from './api';

let cachedSchema = null;

export const getBallotSchema = async () => {
    if (cachedSchema) return cachedSchema;
    const { data } = await governanceAPI.ballotSchema();
    cachedSchema = data;
    return data;
};

/** Random nonce. Replay protection: the backend consumes it once. */
export const generateNonce = () => {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
};

/**
 * Sign a ballot with the wallet. Returns { nonce, signature }.
 *
 * Uses eth_signTypedData_v4 rather than personal_sign so the wallet shows the
 * fields — proposal, choice — instead of an opaque blob. Someone approving a
 * vote should be able to see what they are voting for.
 */
export const signBallot = async ({ proposalId, voter, choice }) => {
    if (!window.ethereum) {
        throw new Error('No se detectó una wallet en este navegador');
    }

    const schema = await getBallotSchema();
    const nonce = generateNonce();

    const payload = {
        domain: schema.domain,
        types: schema.types,
        primaryType: schema.primaryType,
        message: {
            proposalId,
            voter: voter.toLowerCase(),
            choice,
            nonce,
        },
    };

    const signature = await window.ethereum.request({
        method: 'eth_signTypedData_v4',
        params: [voter, JSON.stringify(payload)],
    });

    return { nonce, signature };
};

/** Whether the backend currently rejects unsigned ballots. */
export const isSignatureRequired = async () => {
    const schema = await getBallotSchema();
    return !!schema.signatureRequired;
};
