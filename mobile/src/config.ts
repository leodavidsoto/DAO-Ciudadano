/**
 * App configuration.
 *
 * This experimental client deliberately defaults to a local backend. A signed
 * release must add an explicit, allow-listed environment/base URL instead of
 * inheriting a historical public deployment:
 * - Android emulator reaches the host machine at 10.0.2.2
 * - iOS simulator reaches it at localhost
 */
import { Platform } from 'react-native';

export const API_BASE_URL =
    Platform.OS === 'android'
        ? 'http://10.0.2.2:8000/api'
        : 'http://localhost:8000/api';
