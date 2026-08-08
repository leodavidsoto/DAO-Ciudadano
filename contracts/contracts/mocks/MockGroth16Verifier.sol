// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../IGroth16Verifier.sol";

/**
 * @dev Unit-test verifier. Integration tests use the generated Groth16Verifier.
 */
contract MockGroth16Verifier is IGroth16Verifier {
    bool public result = true;
    bool public shouldRevert;
    bool public enforceExpectedSignals;
    uint256[4] private _expectedSignals;

    error MockVerifierReverted();

    function configure(bool result_, bool shouldRevert_) external {
        result = result_;
        shouldRevert = shouldRevert_;
    }

    function setExpectedPublicSignals(
        uint256[4] calldata expectedSignals,
        bool enforce
    ) external {
        for (uint256 i = 0; i < expectedSignals.length; ++i) {
            _expectedSignals[i] = expectedSignals[i];
        }
        enforceExpectedSignals = enforce;
    }

    function expectedPublicSignals() external view returns (uint256[4] memory) {
        return _expectedSignals;
    }

    function verifyProof(
        uint256[2] calldata,
        uint256[2][2] calldata,
        uint256[2] calldata,
        uint256[4] calldata publicSignals
    ) external view override returns (bool) {
        if (shouldRevert) {
            revert MockVerifierReverted();
        }
        if (enforceExpectedSignals) {
            for (uint256 i = 0; i < publicSignals.length; ++i) {
                if (publicSignals[i] != _expectedSignals[i]) {
                    return false;
                }
            }
        }
        return result;
    }
}
