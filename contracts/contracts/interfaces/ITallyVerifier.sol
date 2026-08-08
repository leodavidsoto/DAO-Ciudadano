// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title ITallyVerifier
 * @notice Verificador Groth16 del circuito de tally de MACI.
 *
 * Interfaz propia y no `IGroth16Verifier` porque la aridad de señales
 * públicas forma parte del contrato con el circuito: el de membresía expone 4
 * y el de tally expone 3. Compartir una interfaz obligaría a que ambos
 * circuitos evolucionaran juntos, y un verificador desplegado con la aridad
 * equivocada revertiría sin explicación.
 *
 * Señales públicas, en este orden:
 *   [0] messageChain  — acumulador de mensajes de la consulta
 *   [1] signUpCount   — número de inscritos
 *   [2] tallyCommitment — compromiso del resultado publicado
 *
 * EL CIRCUITO DE TALLY NO EXISTE TODAVÍA en este repositorio. Esta interfaz
 * fija su frontera para que el contrato pueda escribirse y probarse antes,
 * pero mientras no haya verificador desplegado `publishTally` revierte.
 */
interface ITallyVerifier {
    function verifyProof(
        uint256[2] calldata pA,
        uint256[2][2] calldata pB,
        uint256[2] calldata pC,
        uint256[3] calldata publicSignals
    ) external view returns (bool);
}
