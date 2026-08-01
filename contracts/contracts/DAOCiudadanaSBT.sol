// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./IGroth16Verifier.sol";

/**
 * @title DAOCiudadanaSBT
 * @notice Privacy-preserving, soulbound DAO membership credential.
 *
 * Eligibility is proven with Groth16 without publishing a RUT, an identity
 * hash, an assurance level or a Merkle path. The proof is bound to:
 *
 *  - an issuer-approved eligibility root;
 *  - a permanent, identity-derived nullifier;
 *  - the recipient wallet; and
 *  - a deployment-specific membership scope.
 *
 * The proof is the mint authorization. Any ERC-4337 bundler or relayer may
 * submit it, but changing the recipient invalidates it. A front-runner can at
 * most relay the exact proof to the exact intended recipient.
 */
contract DAOCiudadanaSBT is
    ERC721,
    ERC721URIStorage,
    AccessControl,
    Pausable,
    ReentrancyGuard
{
    uint256 public constant SNARK_SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;
    uint256 public constant REVOCATION_COOLDOWN = 3 days;
    bytes32 public constant MEMBERSHIP_SCOPE_DOMAIN =
        keccak256("DAO_CIUDADANA_MEMBERSHIP_V1");

    bytes32 public constant ROOT_MANAGER_ROLE = keccak256("ROOT_MANAGER_ROLE");
    bytes32 public constant PAUSER_ROLE = keccak256("PAUSER_ROLE");
    bytes32 public constant REVOKER_ROLE = keccak256("REVOKER_ROLE");

    IGroth16Verifier public immutable membershipVerifier;
    uint256 public immutable membershipScope;

    uint256 private _nextTokenId;
    uint256 private _activeSupply;
    string private _membershipTokenURI;

    mapping(address => uint256) private _memberTokens;
    mapping(uint256 => bytes32) private _tokenNullifiers;
    mapping(uint256 => uint256) private _tokenIdentityRoots;
    mapping(bytes32 => bool) private _usedNullifiers;
    mapping(uint256 => bool) private _approvedIdentityRoots;
    mapping(uint256 => uint256) private _revocationRequests;

    event MembershipMinted(
        address indexed member,
        uint256 indexed tokenId,
        bytes32 indexed nullifierHash,
        uint256 identityRoot,
        uint256 timestamp
    );
    event IdentityRootApproved(uint256 indexed identityRoot, address indexed by);
    event IdentityRootRevoked(uint256 indexed identityRoot, address indexed by);
    event RevocationRequested(
        address indexed member,
        uint256 indexed tokenId,
        uint256 executeAfter
    );
    event RevocationCancelled(address indexed member, uint256 indexed tokenId);
    event MembershipRevoked(
        address indexed member,
        uint256 indexed tokenId,
        string reason
    );
    event ContractPaused(address indexed by, string reason);
    event ContractUnpaused(address indexed by);

    error InvalidAdmin();
    error InvalidVerifier(address verifier);
    error InvalidMembershipTokenURI();
    error InvalidRecipient();
    error AlreadyHasMembership(address member);
    error InvalidIdentityRoot(uint256 identityRoot);
    error IdentityRootNotApproved(uint256 identityRoot);
    error InvalidNullifierHash(bytes32 nullifierHash);
    error NullifierAlreadyUsed(bytes32 nullifierHash);
    error InvalidMembershipProof();
    error TokenDoesNotExist(uint256 tokenId);
    error RevocationNotRequested(uint256 tokenId);
    error RevocationCooldownNotPassed(uint256 tokenId, uint256 executeAfter);
    error SoulboundTokenCannotBeTransferred();

    /**
     * @param admin Safe/multisig that receives root, pause and revoke roles.
     * @param verifierAddress Groth16 verifier generated from the exact
     * MembershipEligibility circuit and its production ceremony.
     * @param membershipTokenURI_ Privacy-preserving metadata shared by all SBTs.
     */
    constructor(
        address admin,
        address verifierAddress,
        string memory membershipTokenURI_
    ) ERC721("DAO Ciudadana SBT", "DAOSBT") {
        if (admin == address(0)) {
            revert InvalidAdmin();
        }
        if (verifierAddress.code.length == 0) {
            revert InvalidVerifier(verifierAddress);
        }
        if (bytes(membershipTokenURI_).length == 0) {
            revert InvalidMembershipTokenURI();
        }

        membershipVerifier = IGroth16Verifier(verifierAddress);
        membershipScope =
            (uint256(
                keccak256(
                    abi.encode(
                        MEMBERSHIP_SCOPE_DOMAIN,
                        block.chainid,
                        address(this)
                    )
                )
            ) % (SNARK_SCALAR_FIELD - 1)) +
            1;
        _membershipTokenURI = membershipTokenURI_;

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(ROOT_MANAGER_ROLE, admin);
        _grantRole(PAUSER_ROLE, admin);
        _grantRole(REVOKER_ROLE, admin);
    }

    /**
     * @notice Approves an issuer-curated Merkle root for future proofs.
     */
    function approveIdentityRoot(
        uint256 identityRoot
    ) external onlyRole(ROOT_MANAGER_ROLE) {
        if (identityRoot == 0 || identityRoot >= SNARK_SCALAR_FIELD) {
            revert InvalidIdentityRoot(identityRoot);
        }
        _approvedIdentityRoots[identityRoot] = true;
        emit IdentityRootApproved(identityRoot, msg.sender);
    }

    /**
     * @notice Stops new mints against a root without invalidating existing SBTs.
     */
    function revokeIdentityRoot(
        uint256 identityRoot
    ) external onlyRole(ROOT_MANAGER_ROLE) {
        if (!_approvedIdentityRoots[identityRoot]) {
            revert IdentityRootNotApproved(identityRoot);
        }
        _approvedIdentityRoots[identityRoot] = false;
        emit IdentityRootRevoked(identityRoot, msg.sender);
    }

    /**
     * @notice Mints a membership from an issuer-backed Groth16 proof.
     * @dev Public signals are constructed internally in the circuit's fixed
     * order: [identityRoot, nullifierHash, recipient, membershipScope].
     */
    function mintMembership(
        address to,
        uint256[2] calldata pA,
        uint256[2][2] calldata pB,
        uint256[2] calldata pC,
        bytes32 nullifierHash,
        uint256 identityRoot
    ) external whenNotPaused nonReentrant returns (uint256) {
        if (to == address(0)) {
            revert InvalidRecipient();
        }
        if (_memberTokens[to] != 0) {
            revert AlreadyHasMembership(to);
        }
        if (!_approvedIdentityRoots[identityRoot]) {
            revert IdentityRootNotApproved(identityRoot);
        }

        uint256 nullifierSignal = uint256(nullifierHash);
        if (nullifierSignal == 0 || nullifierSignal >= SNARK_SCALAR_FIELD) {
            revert InvalidNullifierHash(nullifierHash);
        }
        if (_usedNullifiers[nullifierHash]) {
            revert NullifierAlreadyUsed(nullifierHash);
        }

        uint256[4] memory publicSignals = [
            identityRoot,
            nullifierSignal,
            uint256(uint160(to)),
            membershipScope
        ];

        bool proofIsValid;
        try membershipVerifier.verifyProof(pA, pB, pC, publicSignals) returns (
            bool valid
        ) {
            proofIsValid = valid;
        } catch {
            revert InvalidMembershipProof();
        }
        if (!proofIsValid) {
            revert InvalidMembershipProof();
        }

        uint256 tokenId = ++_nextTokenId;

        // Effects before _safeMint's receiver callback.
        _memberTokens[to] = tokenId;
        _tokenNullifiers[tokenId] = nullifierHash;
        _tokenIdentityRoots[tokenId] = identityRoot;
        _usedNullifiers[nullifierHash] = true;
        ++_activeSupply;

        _safeMint(to, tokenId);
        _setTokenURI(tokenId, _membershipTokenURI);

        emit MembershipMinted(
            to,
            tokenId,
            nullifierHash,
            identityRoot,
            block.timestamp
        );

        return tokenId;
    }

    function requestRevocation(
        uint256 tokenId
    ) external onlyRole(REVOKER_ROLE) {
        address member = _ownerOf(tokenId);
        if (member == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }

        uint256 executeAfter = block.timestamp + REVOCATION_COOLDOWN;
        _revocationRequests[tokenId] = executeAfter;
        emit RevocationRequested(member, tokenId, executeAfter);
    }

    function cancelRevocation(
        uint256 tokenId
    ) external onlyRole(REVOKER_ROLE) {
        if (_revocationRequests[tokenId] == 0) {
            revert RevocationNotRequested(tokenId);
        }

        delete _revocationRequests[tokenId];
        emit RevocationCancelled(_ownerOf(tokenId), tokenId);
    }

    function executeRevocation(
        uint256 tokenId,
        string calldata reason
    ) external onlyRole(REVOKER_ROLE) nonReentrant {
        uint256 executeAfter = _revocationRequests[tokenId];
        if (executeAfter == 0) {
            revert RevocationNotRequested(tokenId);
        }
        if (block.timestamp < executeAfter) {
            revert RevocationCooldownNotPassed(tokenId, executeAfter);
        }

        address member = _ownerOf(tokenId);
        _burn(tokenId);

        _memberTokens[member] = 0;
        delete _tokenNullifiers[tokenId];
        delete _tokenIdentityRoots[tokenId];
        delete _revocationRequests[tokenId];
        // _usedNullifiers is deliberately never cleared.
        --_activeSupply;

        emit MembershipRevoked(member, tokenId, reason);
    }

    function pause(string calldata reason) external onlyRole(PAUSER_ROLE) {
        _pause();
        emit ContractPaused(msg.sender, reason);
    }

    function unpause() external onlyRole(PAUSER_ROLE) {
        _unpause();
        emit ContractUnpaused(msg.sender);
    }

    function hasMembership(address member) external view returns (bool) {
        return _memberTokens[member] != 0;
    }

    function getMembershipToken(address member) external view returns (uint256) {
        return _memberTokens[member];
    }

    function getNullifierHash(uint256 tokenId) external view returns (bytes32) {
        if (_ownerOf(tokenId) == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }
        return _tokenNullifiers[tokenId];
    }

    function getIdentityRoot(uint256 tokenId) external view returns (uint256) {
        if (_ownerOf(tokenId) == address(0)) {
            revert TokenDoesNotExist(tokenId);
        }
        return _tokenIdentityRoots[tokenId];
    }

    function isNullifierUsed(bytes32 nullifierHash) external view returns (bool) {
        return _usedNullifiers[nullifierHash];
    }

    function isIdentityRootApproved(
        uint256 identityRoot
    ) external view returns (bool) {
        return _approvedIdentityRoots[identityRoot];
    }

    function getRevocationStatus(
        uint256 tokenId
    ) external view returns (bool requested, uint256 executeAfter) {
        executeAfter = _revocationRequests[tokenId];
        requested = executeAfter != 0;
    }

    function totalSupply() external view returns (uint256) {
        return _activeSupply;
    }

    function totalIssued() external view returns (uint256) {
        return _nextTokenId;
    }

    function membershipTokenURI() external view returns (string memory) {
        return _membershipTokenURI;
    }

    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal override returns (address) {
        address from = _ownerOf(tokenId);
        if (from != address(0) && to != address(0)) {
            revert SoulboundTokenCannotBeTransferred();
        }
        return super._update(to, tokenId, auth);
    }

    function tokenURI(
        uint256 tokenId
    ) public view override(ERC721, ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(
        bytes4 interfaceId
    ) public view override(ERC721, ERC721URIStorage, AccessControl) returns (bool) {
        return super.supportsInterface(interfaceId);
    }
}
