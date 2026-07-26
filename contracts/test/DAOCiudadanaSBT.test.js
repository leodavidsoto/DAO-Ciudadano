const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

/**
 * Test suite for DAOCiudadanaSBT (see ROADMAP task 2.1 / audit finding C-5).
 *
 * Covers the invariants the token's value depends on:
 * - one SBT per wallet, one SBT per identity hash
 * - soulbound (no transfers, ever)
 * - onlyOwner minting and revocation
 * - pause/unpause
 * - revocation lifecycle with 3-day cooldown
 * - identity hashes stay burned forever (no re-registration after revocation)
 */
describe("DAOCiudadanaSBT", function () {
    const IDENTITY_HASH = "a3f8b2c941d05e7f6a1b8c2d3e4f5a6b";
    const OTHER_HASH = "ffeeddccbbaa99887766554433221100";
    const ASSURANCE_AL2 = "AL2";
    const TOKEN_URI = "ipfs://QmTestMetadata";
    const REVOCATION_COOLDOWN = 3 * 24 * 60 * 60; // 3 days in seconds

    async function deployFixture() {
        const [owner, member, otherMember, stranger] = await ethers.getSigners();
        const Factory = await ethers.getContractFactory("DAOCiudadanaSBT");
        const sbt = await Factory.deploy();
        await sbt.waitForDeployment();
        return { sbt, owner, member, otherMember, stranger };
    }

    async function deployWithMintedTokenFixture() {
        const base = await deployFixture();
        const tx = await base.sbt.mintMembership(
            base.member.address,
            IDENTITY_HASH,
            ASSURANCE_AL2,
            TOKEN_URI
        );
        await tx.wait();
        const tokenId = await base.sbt.getMembershipToken(base.member.address);
        return { ...base, tokenId };
    }

    describe("Deployment", function () {
        it("sets deployer as owner, starts unpaused with zero supply", async function () {
            const { sbt, owner } = await loadFixture(deployFixture);
            expect(await sbt.owner()).to.equal(owner.address);
            expect(await sbt.paused()).to.equal(false);
            expect(await sbt.totalSupply()).to.equal(0);
            expect(await sbt.name()).to.equal("DAO Ciudadana SBT");
            expect(await sbt.symbol()).to.equal("DAOSBT");
            expect(await sbt.REVOCATION_COOLDOWN()).to.equal(REVOCATION_COOLDOWN);
        });

        it("supports the ERC721 and ERC721Metadata interfaces", async function () {
            const { sbt } = await loadFixture(deployFixture);
            expect(await sbt.supportsInterface("0x80ac58cd")).to.equal(true);  // ERC721
            expect(await sbt.supportsInterface("0x5b5e139f")).to.equal(true);  // ERC721Metadata
            expect(await sbt.supportsInterface("0x49064906")).to.equal(true);  // ERC4906 (URIStorage)
            expect(await sbt.supportsInterface("0xffffffff")).to.equal(false);
        });
    });

    describe("Minting", function () {
        it("mints successfully and returns the new tokenId", async function () {
            const { sbt, member } = await loadFixture(deployFixture);

            // staticCall exposes the return value without mutating state
            const returnedId = await sbt.mintMembership.staticCall(
                member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI
            );
            expect(returnedId).to.equal(1n);

            await sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI);

            expect(await sbt.ownerOf(1)).to.equal(member.address);
            expect(await sbt.balanceOf(member.address)).to.equal(1);
            expect(await sbt.hasMembership(member.address)).to.equal(true);
            expect(await sbt.getMembershipToken(member.address)).to.equal(1n);
            expect(await sbt.getIdentityHash(1)).to.equal(IDENTITY_HASH);
            expect(await sbt.getAssuranceLevel(1)).to.equal(ASSURANCE_AL2);
            expect(await sbt.isIdentityUsed(IDENTITY_HASH)).to.equal(true);
            expect(await sbt.tokenURI(1)).to.equal(TOKEN_URI);
            expect(await sbt.totalSupply()).to.equal(1);
        });

        it("emits MembershipMinted with member, tokenId, assuranceLevel and timestamp", async function () {
            const { sbt, member } = await loadFixture(deployFixture);

            const tx = await sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI);
            const block = await ethers.provider.getBlock(tx.blockNumber);

            await expect(tx)
                .to.emit(sbt, "MembershipMinted")
                .withArgs(member.address, 1n, ASSURANCE_AL2, block.timestamp);
        });

        it("assigns sequential token ids starting at 1", async function () {
            const { sbt, member, otherMember } = await loadFixture(deployFixture);
            await sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI);
            await sbt.mintMembership(otherMember.address, OTHER_HASH, "AL3", TOKEN_URI);
            expect(await sbt.getMembershipToken(member.address)).to.equal(1n);
            expect(await sbt.getMembershipToken(otherMember.address)).to.equal(2n);
            expect(await sbt.totalSupply()).to.equal(2);
        });

        it("rejects a second SBT for the same wallet", async function () {
            const { sbt, member } = await loadFixture(deployWithMintedTokenFixture);

            await expect(
                sbt.mintMembership(member.address, OTHER_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "AlreadyHasMembership")
                .withArgs(member.address);
        });

        it("rejects an identityHash that is already used", async function () {
            const { sbt, otherMember } = await loadFixture(deployWithMintedTokenFixture);

            await expect(
                sbt.mintMembership(otherMember.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "IdentityAlreadyUsed")
                .withArgs(IDENTITY_HASH);
        });

        it("rejects an empty identityHash", async function () {
            const { sbt, member } = await loadFixture(deployFixture);

            await expect(
                sbt.mintMembership(member.address, "", ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "InvalidIdentityHash");
        });

        it("only the owner can mint", async function () {
            const { sbt, member, stranger } = await loadFixture(deployFixture);

            await expect(
                sbt.connect(stranger).mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount")
                .withArgs(stranger.address);
        });
    });

    describe("Soulbound behavior", function () {
        it("reverts transferFrom between accounts", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await expect(
                sbt.connect(member).transferFrom(member.address, otherMember.address, tokenId)
            ).to.be.revertedWithCustomError(sbt, "SoulboundTokenCannotBeTransferred");
        });

        it("reverts safeTransferFrom between accounts", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await expect(
                sbt.connect(member)["safeTransferFrom(address,address,uint256)"](
                    member.address, otherMember.address, tokenId
                )
            ).to.be.revertedWithCustomError(sbt, "SoulboundTokenCannotBeTransferred");

            await expect(
                sbt.connect(member)["safeTransferFrom(address,address,uint256,bytes)"](
                    member.address, otherMember.address, tokenId, "0x"
                )
            ).to.be.revertedWithCustomError(sbt, "SoulboundTokenCannotBeTransferred");
        });

        it("reverts transfer even by an approved operator", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await sbt.connect(member).approve(otherMember.address, tokenId);
            await expect(
                sbt.connect(otherMember).transferFrom(member.address, otherMember.address, tokenId)
            ).to.be.revertedWithCustomError(sbt, "SoulboundTokenCannotBeTransferred");
        });
    });

    describe("Pausing", function () {
        it("only the owner can pause and unpause", async function () {
            const { sbt, stranger } = await loadFixture(deployFixture);
            await expect(sbt.connect(stranger).pause("attack"))
                .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
            await expect(sbt.connect(stranger).unpause())
                .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
        });

        it("emits ContractPaused / ContractUnpaused", async function () {
            const { sbt, owner } = await loadFixture(deployFixture);
            await expect(sbt.pause("security incident"))
                .to.emit(sbt, "ContractPaused").withArgs(owner.address, "security incident");
            await expect(sbt.unpause())
                .to.emit(sbt, "ContractUnpaused").withArgs(owner.address);
        });

        it("blocks minting while paused and restores it after unpause", async function () {
            const { sbt, member } = await loadFixture(deployFixture);

            await sbt.pause("maintenance");
            await expect(
                sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "EnforcedPause");

            await sbt.unpause();
            await expect(
                sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.emit(sbt, "MembershipMinted");
            expect(await sbt.hasMembership(member.address)).to.equal(true);
        });
    });

    describe("Revocation lifecycle", function () {
        it("only the owner can request, cancel and execute revocations", async function () {
            const { sbt, stranger, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await expect(sbt.connect(stranger).requestRevocation(tokenId))
                .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
            await expect(sbt.connect(stranger).cancelRevocation(tokenId))
                .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
            await expect(sbt.connect(stranger).executeRevocation(tokenId, "x"))
                .to.be.revertedWithCustomError(sbt, "OwnableUnauthorizedAccount");
        });

        it("requestRevocation reverts for a nonexistent token", async function () {
            const { sbt } = await loadFixture(deployFixture);
            await expect(sbt.requestRevocation(999))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist").withArgs(999);
        });

        it("requestRevocation emits event and getRevocationStatus reflects it", async function () {
            const { sbt, member, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            const tx = await sbt.requestRevocation(tokenId);
            const block = await ethers.provider.getBlock(tx.blockNumber);
            const expectedExecuteAfter = BigInt(block.timestamp) + BigInt(REVOCATION_COOLDOWN);

            await expect(tx)
                .to.emit(sbt, "RevocationRequested")
                .withArgs(member.address, tokenId, expectedExecuteAfter);

            const [requested, executeAfter] = await sbt.getRevocationStatus(tokenId);
            expect(requested).to.equal(true);
            expect(executeAfter).to.equal(expectedExecuteAfter);
        });

        it("executeRevocation reverts before the request and during the cooldown", async function () {
            const { sbt, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            // No request yet
            await expect(sbt.executeRevocation(tokenId, "fraud"))
                .to.be.revertedWithCustomError(sbt, "RevocationNotRequested").withArgs(tokenId);

            await sbt.requestRevocation(tokenId);

            // Too early: cooldown has not passed
            await expect(sbt.executeRevocation(tokenId, "fraud"))
                .to.be.revertedWithCustomError(sbt, "RevocationCooldownNotPassed");

            // Still too early one second before the deadline
            await time.increase(REVOCATION_COOLDOWN - 5);
            await expect(sbt.executeRevocation(tokenId, "fraud"))
                .to.be.revertedWithCustomError(sbt, "RevocationCooldownNotPassed");
        });

        it("executes revocation after the 3-day cooldown and clears membership state", async function () {
            const { sbt, member, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await sbt.requestRevocation(tokenId);
            await time.increase(REVOCATION_COOLDOWN + 1);

            await expect(sbt.executeRevocation(tokenId, "identity fraud confirmed"))
                .to.emit(sbt, "MembershipRevoked")
                .withArgs(member.address, tokenId, "identity fraud confirmed");

            // Token no longer exists
            await expect(sbt.ownerOf(tokenId))
                .to.be.revertedWithCustomError(sbt, "ERC721NonexistentToken");
            expect(await sbt.hasMembership(member.address)).to.equal(false);
            expect(await sbt.getMembershipToken(member.address)).to.equal(0n);
            expect(await sbt.balanceOf(member.address)).to.equal(0);

            // Revocation request is cleared as well
            const [requested] = await sbt.getRevocationStatus(tokenId);
            expect(requested).to.equal(false);

            // Per-token metadata views now revert
            await expect(sbt.getIdentityHash(tokenId))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist");
            await expect(sbt.getAssuranceLevel(tokenId))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist");
        });

        it("keeps the identityHash burned after revocation (no re-registration)", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await sbt.requestRevocation(tokenId);
            await time.increase(REVOCATION_COOLDOWN + 1);
            await sbt.executeRevocation(tokenId, "revoked");

            // _usedIdentityHashes is intentionally NOT cleared
            expect(await sbt.isIdentityUsed(IDENTITY_HASH)).to.equal(true);

            // Same identity cannot register again, from any wallet
            await expect(
                sbt.mintMembership(otherMember.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "IdentityAlreadyUsed");
            await expect(
                sbt.mintMembership(member.address, IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI)
            ).to.be.revertedWithCustomError(sbt, "IdentityAlreadyUsed");
        });

        it("allows the same wallet to get a new SBT with a different identityHash after revocation", async function () {
            const { sbt, member, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await sbt.requestRevocation(tokenId);
            await time.increase(REVOCATION_COOLDOWN + 1);
            await sbt.executeRevocation(tokenId, "revoked");

            await sbt.mintMembership(member.address, OTHER_HASH, "AL1", TOKEN_URI);
            expect(await sbt.hasMembership(member.address)).to.equal(true);
            expect(await sbt.getMembershipToken(member.address)).to.equal(2n);
        });

        it("cancelRevocation clears the request and emits event", async function () {
            const { sbt, member, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            await sbt.requestRevocation(tokenId);
            await expect(sbt.cancelRevocation(tokenId))
                .to.emit(sbt, "RevocationCancelled")
                .withArgs(member.address, tokenId);

            const [requested, executeAfter] = await sbt.getRevocationStatus(tokenId);
            expect(requested).to.equal(false);
            expect(executeAfter).to.equal(0n);

            // After cancelling, execution is no longer possible even past the cooldown
            await time.increase(REVOCATION_COOLDOWN + 1);
            await expect(sbt.executeRevocation(tokenId, "late"))
                .to.be.revertedWithCustomError(sbt, "RevocationNotRequested");
            expect(await sbt.hasMembership(member.address)).to.equal(true);
        });

        it("cancelRevocation reverts when no revocation was requested", async function () {
            const { sbt, tokenId } = await loadFixture(deployWithMintedTokenFixture);
            await expect(sbt.cancelRevocation(tokenId))
                .to.be.revertedWithCustomError(sbt, "RevocationNotRequested").withArgs(tokenId);
        });
    });

    describe("View functions on nonexistent tokens", function () {
        it("getIdentityHash reverts with TokenDoesNotExist", async function () {
            const { sbt } = await loadFixture(deployFixture);
            await expect(sbt.getIdentityHash(42))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist").withArgs(42);
        });

        it("getAssuranceLevel reverts with TokenDoesNotExist", async function () {
            const { sbt } = await loadFixture(deployFixture);
            await expect(sbt.getAssuranceLevel(42))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist").withArgs(42);
        });

        it("hasMembership / getMembershipToken / isIdentityUsed return empty defaults", async function () {
            const { sbt, stranger } = await loadFixture(deployFixture);
            expect(await sbt.hasMembership(stranger.address)).to.equal(false);
            expect(await sbt.getMembershipToken(stranger.address)).to.equal(0n);
            expect(await sbt.isIdentityUsed("never-used-hash")).to.equal(false);
        });
    });

    describe("totalSupply accounting (audit finding M-9)", function () {
        it("does NOT decrease after a revocation — documented over-count", async function () {
            // totalSupply() returns _nextTokenId, which never decreases on burn.
            // This over-counts members after revocations (AUDIT.md M-9).
            // This test pins the current behavior; if M-9 gets fixed, update it.
            const { sbt, tokenId } = await loadFixture(deployWithMintedTokenFixture);

            expect(await sbt.totalSupply()).to.equal(1);
            await sbt.requestRevocation(tokenId);
            await time.increase(REVOCATION_COOLDOWN + 1);
            await sbt.executeRevocation(tokenId, "revoked");

            // Still 1 even though zero tokens exist
            expect(await sbt.totalSupply()).to.equal(1);
        });
    });

    describe("Checks-effects-interactions in mintMembership", function () {
        it("membership state is fully written before the receiver callback runs", async function () {
            // slither reentrancy-no-eth: _safeMint invokes onERC721Received on
            // contract receivers. The receiver must already see consistent
            // membership state during that callback.
            const { sbt } = await loadFixture(deployFixture);

            const Probe = await ethers.getContractFactory("ReceiverProbe");
            const probe = await Probe.deploy();
            await probe.waitForDeployment();

            await sbt.mintMembership(
                await probe.getAddress(), IDENTITY_HASH, ASSURANCE_AL2, TOKEN_URI
            );

            expect(await probe.sawMembershipDuringCallback()).to.equal(true);
            expect(await probe.tokenIdDuringCallback()).to.equal(1n);
        });
    });
});
