pragma circom 2.2.0;

include "circomlib/circuits/poseidon.circom";

/**
 * Privacy-preserving DAO membership eligibility proof.
 *
 * The issuer must validate civil identity off-chain and insert at most one
 * commitment per citizen in its Merkle tree:
 *
 *   leaf = Poseidon(identitySecret, recipient, scope)
 *
 * The identitySecret and Merkle path remain private. The nullifier excludes
 * recipient deliberately, so moving the same identity to a different wallet
 * cannot create a second membership:
 *
 *   nullifierHash = Poseidon(identitySecret, scope)
 *
 * Public signal order is a protocol boundary shared with
 * DAOCiudadanaSBT.mintMembership:
 *   [identityRoot, nullifierHash, recipient, scope]
 */
template MembershipEligibility(levels) {
    // Private witness.
    signal input identitySecret;
    signal input pathElements[levels];
    signal input pathIndices[levels];

    // Public inputs.
    signal input identityRoot;
    signal input nullifierHash;
    signal input recipient;
    signal input scope;

    // A zero secret would create a shared, trivially predictable credential.
    signal secretInverse;
    secretInverse <-- 1 / identitySecret;
    identitySecret * secretInverse === 1;

    component nullifierHasher = Poseidon(2);
    nullifierHasher.inputs[0] <== identitySecret;
    nullifierHasher.inputs[1] <== scope;
    nullifierHasher.out === nullifierHash;

    // Binding recipient into the issuer-approved leaf prevents a mempool
    // observer from redirecting a valid proof to another wallet.
    component leafHasher = Poseidon(3);
    leafHasher.inputs[0] <== identitySecret;
    leafHasher.inputs[1] <== recipient;
    leafHasher.inputs[2] <== scope;

    signal hashes[levels + 1];
    signal left[levels];
    signal right[levels];
    component levelHashers[levels];

    hashes[0] <== leafHasher.out;

    for (var i = 0; i < levels; i++) {
        pathIndices[i] * (pathIndices[i] - 1) === 0;

        left[i] <== hashes[i]
            + pathIndices[i] * (pathElements[i] - hashes[i]);
        right[i] <== pathElements[i]
            + pathIndices[i] * (hashes[i] - pathElements[i]);

        levelHashers[i] = Poseidon(2);
        levelHashers[i].inputs[0] <== left[i];
        levelHashers[i].inputs[1] <== right[i];
        hashes[i + 1] <== levelHashers[i].out;
    }

    hashes[levels] === identityRoot;
}

// 25 levels support up to 33,554,432 issuer commitments.
component main {public [identityRoot, nullifierHash, recipient, scope]} =
    MembershipEligibility(25);
