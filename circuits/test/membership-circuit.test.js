"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const snarkjs = require("snarkjs");

const circuitDir = path.resolve(__dirname, "..");
const fixture = JSON.parse(
    fs.readFileSync(
        path.join(__dirname, "fixtures", "membership-proof.json"),
        "utf8"
    )
);
const verificationKey = JSON.parse(
    fs.readFileSync(
        path.join(circuitDir, "build", "verification_key.json"),
        "utf8"
    )
);

async function main() {
    assert.deepEqual(fixture.signalOrder, [
        "identityRoot",
        "nullifierHash",
        "recipient",
        "scope",
    ]);

    assert.equal(
        await snarkjs.groth16.verify(
            verificationKey,
            fixture.publicSignals,
            fixture.proof
        ),
        true,
        "fixture proof must verify"
    );

    for (const signalIndex of [0, 1, 2, 3]) {
        const tamperedSignals = [...fixture.publicSignals];
        tamperedSignals[signalIndex] = (
            BigInt(tamperedSignals[signalIndex]) + 1n
        ).toString();
        assert.equal(
            await snarkjs.groth16.verify(
                verificationKey,
                tamperedSignals,
                fixture.proof
            ),
            false,
            `tampering public signal ${signalIndex} must invalidate the proof`
        );
    }

    process.stdout.write(
        "Groth16 fixture verified; root, nullifier, recipient and scope are bound.\n"
    );
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
