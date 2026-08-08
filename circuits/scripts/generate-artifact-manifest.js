"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "..", "..");
const outputPath = path.join(repositoryRoot, "circuits", "artifact-manifest.json");
const artifactPaths = [
    "circuits/verify_identity.circom",
    "circuits/build/verify_identity_js/verify_identity.wasm",
    "circuits/build/verify_identity_final.zkey",
    "circuits/build/verification_key.json",
    "contracts/contracts/Verifier.sol",
];

const files = {};
for (const relativePath of artifactPaths) {
    const contents = fs.readFileSync(path.join(repositoryRoot, relativePath));
    files[relativePath] = {
        bytes: contents.length,
        sha256: crypto.createHash("sha256").update(contents).digest("hex"),
    };
}

const manifest = {
    protocol: "dao-ciudadana-membership-groth16-v1",
    productionReady: false,
    trustedSetup: "single-host-development-integration",
    circuit: {
        name: "MembershipEligibility",
        depth: 25,
        nonlinearConstraints: 6658,
        scopeBinding: "keccak256(protocolVersion, chainId, membershipContract)",
        publicSignals: [
            "identityRoot",
            "nullifierHash",
            "recipient",
            "scope",
        ],
    },
    toolchain: {
        circom2: "0.2.23",
        circomlib: "2.0.5",
        snarkjs: "0.7.6",
    },
    files,
};

fs.writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
process.stdout.write(`Wrote ${outputPath}\n`);
