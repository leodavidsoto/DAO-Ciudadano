// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../interfaces/ITallyVerifier.sol";

/**
 * @dev Verificador de tally para tests unitarios. El circuito real todavía no
 * existe; esto permite probar la lógica del coordinador sin fingir que sí.
 */
contract MockTallyVerifier is ITallyVerifier {
    bool public result = true;
    bool public shouldRevert;
    uint256[3] private _lastSignals;

    error MockTallyVerifierReverted();

    function configure(bool result_, bool shouldRevert_) external {
        result = result_;
        shouldRevert = shouldRevert_;
    }

    function lastPublicSignals() external view returns (uint256[3] memory) {
        return _lastSignals;
    }

    function verifyProof(
        uint256[2] calldata,
        uint256[2][2] calldata,
        uint256[2] calldata,
        uint256[3] calldata publicSignals
    ) external view override returns (bool) {
        if (shouldRevert) revert MockTallyVerifierReverted();
        return result;
    }

    /// Variante que registra las señales, para poder afirmarlas en los tests.
    function verifyAndRecord(uint256[3] calldata publicSignals) external {
        for (uint256 i = 0; i < publicSignals.length; ++i) {
            _lastSignals[i] = publicSignals[i];
        }
    }
}
