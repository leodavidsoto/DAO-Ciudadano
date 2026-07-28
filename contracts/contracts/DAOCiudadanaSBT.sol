// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title DAOCiudadanaSBT
 * @dev Soulbound Token (SBT) for DAO Ciudadana membership
 * @notice Security-hardened version with anti-fraud mechanisms
 * 
 * Features:
 * - Non-transferable (soulbound)
 * - One per wallet (enforced)
 * - Contains identity hash (not PII)
 * - Pausable for emergencies
 * - Reentrancy protected
 * - Revocable by admin with cooldown
 *
 * Roles (ADR 0001, decision D-1): minting is separated from administration so
 * a leaked minter key can issue memberships but cannot revoke, pause or grant
 * roles. DEFAULT_ADMIN_ROLE is meant to be held by a multisig, never an EOA.
 */
contract DAOCiudadanaSBT is ERC721, ERC721URIStorage, AccessControl, Pausable, ReentrancyGuard {
    /// @dev May mint memberships. Nothing else.
    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");
    /// @dev May pause and revoke. Held by a multisig.
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN_ROLE");

    uint256 private _nextTokenId;
    
    // === Mappings ===
    
    // Wallet to token ID (only one SBT per wallet)
    mapping(address => uint256) private _memberTokens;
    
    // Token ID to identity hash
    mapping(uint256 => bytes32) private _identityHashes;
    
    // Token ID to assurance level
    mapping(uint256 => string) private _assuranceLevels;
    
    // Identity hash to boolean (prevents same identity from getting multiple SBTs)
    mapping(bytes32 => bool) private _usedIdentityHashes;
    
    // Revocation requests with cooldown
    mapping(uint256 => uint256) private _revocationRequests;
    
    // === Constants ===
    
    uint256 public constant REVOCATION_COOLDOWN = 3 days;
    
    // === Events ===
    
    event MembershipMinted(
        address indexed member, 
        uint256 indexed tokenId, 
        string assuranceLevel,
        uint256 timestamp
    );
    
    event RevocationRequested(
        address indexed member, 
        uint256 indexed tokenId,
        uint256 executeAfter
    );
    
    event RevocationCancelled(
        address indexed member, 
        uint256 indexed tokenId
    );
    
    event MembershipRevoked(
        address indexed member, 
        uint256 indexed tokenId,
        string reason
    );
    
    event ContractPaused(address indexed by, string reason);
    event ContractUnpaused(address indexed by);
    
    // === Errors ===
    
    error AlreadyHasMembership(address member);
    error IdentityAlreadyUsed(bytes32 identityHash);
    error InvalidIdentityHash();
    error TokenDoesNotExist(uint256 tokenId);
    error RevocationNotRequested(uint256 tokenId);
    error RevocationCooldownNotPassed(uint256 tokenId, uint256 executeAfter);
    error SoulboundTokenCannotBeTransferred();
    error InvalidRoleAddress();
    
    constructor(address admin, address minter) ERC721("DAO Ciudadana SBT", "DAOSBT") {
        if (admin == address(0) || minter == address(0)) revert InvalidRoleAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ADMIN_ROLE, admin);
        _grantRole(MINTER_ROLE, minter);
    }
    
    // === Core Functions ===
    
    /**
     * @dev Mint a new SBT for a member
     * @param to Member's wallet address
     * @param identityHash Hash of verified identity (not PII)
     * @param assuranceLevel Level of identity verification (AL1, AL2, AL3)
     * @param uri Token metadata URI
     */
    function mintMembership(
        address to,
        bytes32 identityHash,
        string memory assuranceLevel,
        string memory uri
    ) public onlyRole(MINTER_ROLE) whenNotPaused nonReentrant returns (uint256) {
        // Validate inputs
        if (_memberTokens[to] != 0) {
            revert AlreadyHasMembership(to);
        }
        if (identityHash == bytes32(0)) {
            revert InvalidIdentityHash();
        }
        if (_usedIdentityHashes[identityHash]) {
            revert IdentityAlreadyUsed(identityHash);
        }
        
        uint256 tokenId = ++_nextTokenId;

        // Effects before interaction: _safeMint calls onERC721Received on
        // contract receivers, which could observe (or reenter through)
        // half-updated membership state if these writes came after it.
        _memberTokens[to] = tokenId;
        _identityHashes[tokenId] = identityHash;
        _assuranceLevels[tokenId] = assuranceLevel;
        _usedIdentityHashes[identityHash] = true;

        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);

        emit MembershipMinted(to, tokenId, assuranceLevel, block.timestamp);

        return tokenId;
    }
    
    /**
     * @dev Request membership revocation (starts cooldown)
     * @param tokenId Token ID to revoke
     */
    function requestRevocation(uint256 tokenId) public onlyRole(ADMIN_ROLE) {
        if (_ownerOf(tokenId) == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }
        
        uint256 executeAfter = block.timestamp + REVOCATION_COOLDOWN;
        _revocationRequests[tokenId] = executeAfter;
        
        emit RevocationRequested(_ownerOf(tokenId), tokenId, executeAfter);
    }
    
    /**
     * @dev Cancel a revocation request
     * @param tokenId Token ID to cancel revocation for
     */
    function cancelRevocation(uint256 tokenId) public onlyRole(ADMIN_ROLE) {
        if (_revocationRequests[tokenId] == 0) {
            revert RevocationNotRequested(tokenId);
        }
        
        delete _revocationRequests[tokenId];
        
        emit RevocationCancelled(_ownerOf(tokenId), tokenId);
    }
    
    /**
     * @dev Execute membership revocation (after cooldown)
     * @param tokenId Token ID to revoke
     * @param reason Reason for revocation
     */
    function executeRevocation(uint256 tokenId, string memory reason) public onlyRole(ADMIN_ROLE) nonReentrant {
        uint256 executeAfter = _revocationRequests[tokenId];
        
        if (executeAfter == 0) {
            revert RevocationNotRequested(tokenId);
        }
        if (block.timestamp < executeAfter) {
            revert RevocationCooldownNotPassed(tokenId, executeAfter);
        }
        
        address member = _ownerOf(tokenId);
        // NOTE: _usedIdentityHashes is deliberately NOT cleared, so the same
        // identity cannot obtain a new membership after a revocation.
        
        // Burn token
        _burn(tokenId);
        
        // Clear mappings
        _memberTokens[member] = 0;
        delete _identityHashes[tokenId];
        delete _assuranceLevels[tokenId];
        delete _revocationRequests[tokenId];
        // Note: _usedIdentityHashes is NOT cleared to prevent re-registration
        
        emit MembershipRevoked(member, tokenId, reason);
    }
    
    // === Emergency Functions ===
    
    /**
     * @dev Pause all minting operations
     */
    function pause(string memory reason) public onlyRole(ADMIN_ROLE) {
        _pause();
        emit ContractPaused(msg.sender, reason);
    }
    
    /**
     * @dev Unpause minting operations
     */
    function unpause() public onlyRole(ADMIN_ROLE) {
        _unpause();
        emit ContractUnpaused(msg.sender);
    }
    
    // === View Functions ===
    
    /**
     * @dev Check if address has membership
     */
    function hasMembership(address member) public view returns (bool) {
        return _memberTokens[member] != 0;
    }
    
    /**
     * @dev Get member's token ID
     */
    function getMembershipToken(address member) public view returns (uint256) {
        return _memberTokens[member];
    }
    
    /**
     * @dev Get identity hash for a token
     */
    function getIdentityHash(uint256 tokenId) public view returns (bytes32) {
        if (_ownerOf(tokenId) == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }
        return _identityHashes[tokenId];
    }
    
    /**
     * @dev Get assurance level for a token
     */
    function getAssuranceLevel(uint256 tokenId) public view returns (string memory) {
        if (_ownerOf(tokenId) == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }
        return _assuranceLevels[tokenId];
    }
    
    /**
     * @dev Check if identity hash has been used
     */
    function isIdentityUsed(bytes32 identityHash) public view returns (bool) {
        return _usedIdentityHashes[identityHash];
    }
    
    /**
     * @dev Get revocation request status
     */
    function getRevocationStatus(uint256 tokenId) public view returns (bool requested, uint256 executeAfter) {
        executeAfter = _revocationRequests[tokenId];
        requested = executeAfter != 0;
    }
    
    /**
     * @dev Get total supply of tokens
     */
    function totalSupply() public view returns (uint256) {
        return _nextTokenId;
    }
    
    // === Soulbound Override ===
    
    /**
     * @dev Override to make tokens non-transferable (soulbound)
     */
    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal virtual override returns (address) {
        address from = _ownerOf(tokenId);
        
        // Allow minting (from == address(0)) and burning (to == address(0))
        // But prevent transfers between addresses
        if (from != address(0) && to != address(0)) {
            revert SoulboundTokenCannotBeTransferred();
        }
        
        return super._update(to, tokenId, auth);
    }
    
    // === Required Overrides ===
    
    function tokenURI(uint256 tokenId) public view override(ERC721, ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }
    
    function supportsInterface(bytes4 interfaceId) public view override(ERC721, ERC721URIStorage, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}
