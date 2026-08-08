// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @dev Registro de membresía para tests unitarios de MACICoordinator.
 *
 * El SBT real exige una prueba Groth16 completa para mintear; montarlo aquí
 * probaría el SBT, no al coordinador. Esto aísla lo que se está probando.
 */
contract MockMembershipRegistry {
    mapping(address => bool) private _members;

    function setMember(address member, bool value) external {
        _members[member] = value;
    }

    function hasMembership(address member) external view returns (bool) {
        return _members[member];
    }
}
