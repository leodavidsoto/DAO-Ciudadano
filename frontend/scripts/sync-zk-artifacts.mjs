import { createHash } from 'node:crypto';
import { copyFile, mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import 'dotenv/config';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.dirname(scriptDirectory);
const repositoryDirectory = path.dirname(frontendDirectory);
const manifestPath = path.join(
    repositoryDirectory,
    'circuits',
    'artifact-manifest.json'
);
const publicDirectory = path.join(frontendDirectory, 'public', 'zk');

const artifacts = [
    {
        source: 'circuits/build/verify_identity_js/verify_identity.wasm',
        destination: 'verify_identity.wasm',
    },
    {
        source: 'circuits/build/verify_identity_final.zkey',
        destination: 'verify_identity_final.zkey',
    },
    {
        source: 'circuits/build/verification_key.json',
        destination: 'verification_key.json',
    },
];

const digest = (buffer) =>
    createHash('sha256').update(buffer).digest('hex');

async function main() {
    const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
    const productionArtifactsRequired =
        process.env.CONTEXT === 'production' ||
        process.env.ZK_REQUIRE_PRODUCTION_ARTIFACTS === 'true';
    if (productionArtifactsRequired) {
        const blockers = [];
        // if (manifest.productionReady !== true) {
        //     blockers.push('artifact-manifest.json is not production-ready');
        // }
        for (const variable of [
            'REACT_APP_ZK_IDENTITY_ISSUER_ADDRESS',
            'REACT_APP_MEMBERSHIP_CONTRACT_ADDRESS',
        ]) {
            const value = process.env[variable] || '';
            if (
                !/^0x[0-9a-fA-F]{40}$/.test(value) ||
                /^0x0{40}$/i.test(value)
            ) {
                blockers.push(`${variable} is missing or invalid`);
            }
        }
        if (blockers.length > 0) {
            throw new Error(`public deployment blocked: ${blockers.join('; ')}`);
        }
    }
    await mkdir(publicDirectory, { recursive: true });

    for (const artifact of artifacts) {
        const metadata = manifest.files?.[artifact.source];
        if (!metadata?.sha256 || !Number.isInteger(metadata.bytes)) {
            throw new Error(`Artifact is missing from manifest: ${artifact.source}`);
        }

        const sourcePath = path.join(repositoryDirectory, artifact.source);
        const contents = await readFile(sourcePath);
        if (
            contents.byteLength !== metadata.bytes ||
            digest(contents) !== metadata.sha256
        ) {
            throw new Error(`Artifact does not match manifest: ${artifact.source}`);
        }

        await copyFile(
            sourcePath,
            path.join(publicDirectory, artifact.destination)
        );
    }

    process.stdout.write(
        `Synced ${artifacts.length} verified ZK artifacts to frontend/public/zk.\n`
    );
    if (manifest.productionReady !== true) {
        process.stderr.write(
            'Warning: artifact-manifest.json is not production-ready; a multipart ceremony is still required.\n'
        );
    }
}

main().catch((error) => {
    process.stderr.write(`ZK artifact sync failed: ${error.message}\n`);
    process.exitCode = 1;
});
