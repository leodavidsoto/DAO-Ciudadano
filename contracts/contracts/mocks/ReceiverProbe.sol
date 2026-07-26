// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/IERC721Receiver.sol";

interface IMembershipView {
    function hasMembership(address member) external view returns (bool);

    function getMembershipToken(address member) external view returns (uint256);
}

/**
 * @dev Test-only receiver. Records what the SBT contract's membership state
 * looked like at the exact moment onERC721Received fired, to verify the
 * checks-effects-interactions ordering in mintMembership (slither
 * reentrancy-no-eth finding): a receiver must never observe half-updated
 * membership state during the mint callback.
 */
contract ReceiverProbe is IERC721Receiver {
    bool public sawMembershipDuringCallback;
    uint256 public tokenIdDuringCallback;

    function onERC721Received(
        address,
        address,
        uint256,
        bytes calldata
    ) external override returns (bytes4) {
        sawMembershipDuringCallback = IMembershipView(msg.sender).hasMembership(address(this));
        tokenIdDuringCallback = IMembershipView(msg.sender).getMembershipToken(address(this));
        return IERC721Receiver.onERC721Received.selector;
    }
}
