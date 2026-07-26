/**
 * App configuration.
 *
 * The production backend on Render is suspended (HTTP 503 — AUDIT M-15),
 * so pointing at it by default would make every request fail. Default to a
 * local development backend until a live environment exists again:
 * - Android emulator reaches the host machine at 10.0.2.2
 * - iOS simulator reaches it at localhost
 */
import { Platform } from 'react-native';

export const API_BASE_URL =
    Platform.OS === 'android'
        ? 'http://10.0.2.2:8000/api'
        : 'http://localhost:8000/api';
