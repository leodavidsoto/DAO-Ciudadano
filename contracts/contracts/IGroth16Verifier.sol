// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IGroth16Verifier
 * @notice snarkjs-compatible verifier for MembershipEligibility.circom.
 *
 * Public signal order is immutable protocol data:
 * [identityRoot, nullifierHash, recipient, membershipScope].
 */
interface IGroth16Verifier {
    function verifyProof(
        uint256[2] calldata pA,
        uint256[2][2] calldata pB,
        uint256[2] calldata pC,
        uint256[4] calldata publicSignals
    ) external view returns (bool);
}
