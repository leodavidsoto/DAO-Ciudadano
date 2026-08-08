"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { buildPoseidon } = require("circomlibjs");
const snarkjs = require("snarkjs");

const CIRCUIT_DEPTH = 25;
const FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;

// Hardhat's deterministic second account. This is deliberately public test
// material and must never be reused as a real identity secret or ceremony key.
const RECIPIENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8";
// Hardhat signer #9 deploys Verifier at nonce 0 and the SBT at nonce 1.
// DAOCiudadanaSBT derives this scope from version + chain 31337 + its address.
const MEMBERSHIP_CONTRACT = "0xA15BB66138824a1c7167f5E85b957d04Dd34E468";
const IDENTITY_SECRET = 18374686479671623683n;
const MEMBERSHIP_SCOPE =
    16645906639000314148974453730666249407391726919646577242780652979940179738392n;

const circuitDir = path.resolve(__dirname, "..");
const wasmPath = path.join(
    circuitDir,
    "build",
    "verify_identity_js",
    "verify_identity.wasm"
);
const zkeyPath = path.join(
    circuitDir,
    "build",
    "verify_identity_final.zkey"
);
const verificationKeyPath = path.join(
    circuitDir,
    "build",
    "verification_key.json"
);
const fixturePath = path.join(
    circuitDir,
    "test",
    "fixtures",
    "membership-proof.json"
);

function toBytes32(value) {
    return `0x${value.toString(16).padStart(64, "0")}`;
}

async function main() {
    for (const artifact of [wasmPath, zkeyPath, verificationKeyPath]) {
        assert.ok(fs.existsSync(artifact), `Missing artifact: ${artifact}`);
    }

    const poseidon = await buildPoseidon();
    const poseidonHash = (inputs) =>
        BigInt(poseidon.F.toString(poseidon(inputs)));

    const recipientSignal = BigInt(RECIPIENT);
    assert.ok(recipientSignal < FIELD);
    assert.ok(MEMBERSHIP_SCOPE > 0n && MEMBERSHIP_SCOPE < FIELD);

    // The fixture tree has one credential at index zero. Empty leaves are 0;
    // zeroHashes[i] is the empty subtree root at level i.
    const zeroHashes = [0n];
    for (let level = 0; level < CIRCUIT_DEPTH; level += 1) {
        zeroHashes.push(
            poseidonHash([zeroHashes[level], zeroHashes[level]])
        );
    }

    const leaf = poseidonHash([
        IDENTITY_SECRET,
        recipientSignal,
        MEMBERSHIP_SCOPE,
    ]);
    const nullifierHash = poseidonHash([
        IDENTITY_SECRET,
        MEMBERSHIP_SCOPE,
    ]);

    const pathElements = [];
    const pathIndices = [];
    let identityRoot = leaf;
    for (let level = 0; level < CIRCUIT_DEPTH; level += 1) {
        pathElements.push(zeroHashes[level].toString());
        pathIndices.push(0);
        identityRoot = poseidonHash([identityRoot, zeroHashes[level]]);
    }

    const input = {
        identitySecret: IDENTITY_SECRET.toString(),
        pathElements,
        pathIndices,
        identityRoot: identityRoot.toString(),
        nullifierHash: nullifierHash.toString(),
        recipient: recipientSignal.toString(),
        scope: MEMBERSHIP_SCOPE.toString(),
    };

    const { proof, publicSignals } = await snarkjs.groth16.fullProve(
        input,
        wasmPath,
        zkeyPath
    );

    const expectedSignals = [
        identityRoot.toString(),
        nullifierHash.toString(),
        recipientSignal.toString(),
        MEMBERSHIP_SCOPE.toString(),
    ];
    assert.deepEqual(publicSignals, expectedSignals);

    const verificationKey = JSON.parse(
        fs.readFileSync(verificationKeyPath, "utf8")
    );
    assert.equal(
        await snarkjs.groth16.verify(verificationKey, publicSignals, proof),
        true,
        "Generated proof did not verify"
    );

    // Delegate the Fq2 coordinate order to snarkjs, the same path used by the
    // browser integration. Hand-reversing pi_b is easy to get subtly wrong.
    const solidityCalldata = await snarkjs.groth16.exportSolidityCallData(
        proof,
        publicSignals
    );
    const [pA, pB, pC, solidityPublicSignals] = JSON.parse(
        `[${solidityCalldata}]`
    );
    assert.deepEqual(
        solidityPublicSignals.map((value) => BigInt(value).toString()),
        publicSignals
    );
    const solidityProof = { pA, pB, pC };

    const fixture = {
        warning: "Public deterministic integration fixture; never use its secret in production.",
        circuit: "MembershipEligibility(25)",
        signalOrder: [
            "identityRoot",
            "nullifierHash",
            "recipient",
            "scope",
        ],
        recipient: RECIPIENT,
        membershipContract: MEMBERSHIP_CONTRACT,
        membershipScope: MEMBERSHIP_SCOPE.toString(),
        identityRoot: identityRoot.toString(),
        nullifierHash: toBytes32(nullifierHash),
        publicSignals,
        proof,
        solidityProof,
    };

    fs.mkdirSync(path.dirname(fixturePath), { recursive: true });
    fs.writeFileSync(fixturePath, `${JSON.stringify(fixture, null, 2)}\n`);
    process.stdout.write(`Wrote ${fixturePath}\n`);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
