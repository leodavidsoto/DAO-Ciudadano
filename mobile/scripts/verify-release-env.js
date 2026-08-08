#!/usr/bin/env node

'use strict';

const value = process.env.DAO_API_BASE_URL?.trim();

if (!value) {
    throw new Error('DAO_API_BASE_URL is required for a native release build.');
}

let url;
try {
    url = new URL(value);
} catch {
    throw new Error('DAO_API_BASE_URL must be an absolute URL.');
}

if (url.protocol !== 'https:') {
    throw new Error('DAO_API_BASE_URL must use HTTPS.');
}
if (url.username || url.password) {
    throw new Error('DAO_API_BASE_URL must not contain credentials.');
}

const forbiddenHosts = new Set(['localhost', '127.0.0.1', '::1', '10.0.2.2']);
if (forbiddenHosts.has(url.hostname.toLowerCase())) {
    throw new Error('DAO_API_BASE_URL must not point to a loopback host.');
}
if (
    process.env.DAO_MOBILE_DISTRIBUTION === 'true' &&
    url.hostname.toLowerCase().endsWith('.invalid')
) {
    throw new Error('Distribution builds require a real API hostname.');
}

console.log(`Release API origin validated: ${url.origin}`);
