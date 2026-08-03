import { Platform } from 'react-native';

declare const process: {
    env: {
        DAO_API_BASE_URL?: string;
    };
};

const LOCAL_API_BASE_URL =
    Platform.OS === 'android'
        ? 'http://10.0.2.2:8000/api'
        : 'http://localhost:8000/api';

export function resolveApiBaseUrl(
    configuredUrl: string | undefined,
    development: boolean,
): string {
    const candidate = configuredUrl?.trim();

    if (!candidate) {
        if (development) {
            return LOCAL_API_BASE_URL;
        }
        throw new Error(
            'DAO_API_BASE_URL is required in native release builds.',
        );
    }

    let parsed: URL;
    try {
        parsed = new URL(candidate);
    } catch {
        throw new Error('DAO_API_BASE_URL must be an absolute URL.');
    }

    if (!development && parsed.protocol !== 'https:') {
        throw new Error('DAO_API_BASE_URL must use HTTPS in release builds.');
    }
    if (parsed.username || parsed.password) {
        throw new Error('DAO_API_BASE_URL must not contain credentials.');
    }

    return candidate.replace(/\/$/, '');
}

/**
 * Babel replaces DAO_API_BASE_URL while producing the native JS bundle. Local
 * debug sessions retain emulator/simulator loopback defaults; release bundles
 * fail closed unless CI injects an explicit HTTPS endpoint.
 */
export const API_BASE_URL = resolveApiBaseUrl(
    process.env.DAO_API_BASE_URL,
    __DEV__,
);
