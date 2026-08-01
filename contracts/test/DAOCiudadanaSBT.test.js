const { expect } = require("chai");
const { ethers } = require("hardhat");
const {
    loadFixture,
    time,
} = require("@nomicfoundation/hardhat-toolbox/network-helpers");

const proofFixture = require("../../circuits/test/fixtures/membership-proof.json");

describe("DAOCiudadanaSBT — wallet-bound Groth16 membership", function () {
    this.timeout(120_000);

    const SNARK_SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617n;
    const MEMBERSHIP_SCOPE = BigInt(proofFixture.membershipScope);
    const ROOT = 987654321n;
    const OTHER_ROOT = 987654322n;
    const NULLIFIER = ethers.zeroPadValue(ethers.toBeHex(111111n), 32);
    const OTHER_NULLIFIER = ethers.zeroPadValue(ethers.toBeHex(222222n), 32);
    const TOKEN_URI = "ipfs://dao-ciudadana/membership-v1";
    const REVOCATION_COOLDOWN = 3 * 24 * 60 * 60;

    const P_A = [1n, 2n];
    const P_B = [
        [3n, 4n],
        [5n, 6n],
    ];
    const P_C = [7n, 8n];

    async function deployFixture() {
        const [admin, member, otherMember, stranger, roleAccount] =
            await ethers.getSigners();

        const MockVerifier = await ethers.getContractFactory(
            "MockGroth16Verifier"
        );
        const verifier = await MockVerifier.deploy();
        await verifier.waitForDeployment();

        const Factory = await ethers.getContractFactory("DAOCiudadanaSBT");
        const sbt = await Factory.deploy(
            admin.address,
            await verifier.getAddress(),
            TOKEN_URI
        );
        await sbt.waitForDeployment();
        await sbt.approveIdentityRoot(ROOT);

        return {
            sbt,
            verifier,
            admin,
            member,
            otherMember,
            stranger,
            roleAccount,
            ROOT_MANAGER_ROLE: await sbt.ROOT_MANAGER_ROLE(),
            PAUSER_ROLE: await sbt.PAUSER_ROLE(),
            REVOKER_ROLE: await sbt.REVOKER_ROLE(),
            DEFAULT_ADMIN_ROLE: await sbt.DEFAULT_ADMIN_ROLE(),
        };
    }

    async function mint(
        sbt,
        recipient,
        {
            caller,
            nullifier = NULLIFIER,
            root = ROOT,
            pA = P_A,
            pB = P_B,
            pC = P_C,
        } = {}
    ) {
        const connected = caller ? sbt.connect(caller) : sbt;
        return connected.mintMembership(
            recipient,
            pA,
            pB,
            pC,
            nullifier,
            root
        );
    }

    async function deployMintedFixture() {
        const base = await deployFixture();
        await mint(base.sbt, base.member.address);
        return {
            ...base,
            tokenId: await base.sbt.getMembershipToken(base.member.address),
        };
    }

    async function deployRealVerifierFixture() {
        const signers = await ethers.getSigners();
        const [admin, member, otherMember, stranger] = signers;
        const zkDeployer = signers[9];
        expect(member.address).to.equal(proofFixture.recipient);

        const Verifier = await ethers.getContractFactory(
            "Groth16Verifier",
            zkDeployer
        );
        const verifier = await Verifier.deploy();
        await verifier.waitForDeployment();

        const Factory = await ethers.getContractFactory(
            "DAOCiudadanaSBT",
            zkDeployer
        );
        const sbt = await Factory.deploy(
            admin.address,
            await verifier.getAddress(),
            TOKEN_URI
        );
        await sbt.waitForDeployment();
        expect(await sbt.getAddress()).to.equal(proofFixture.membershipContract);
        expect(await sbt.membershipScope()).to.equal(MEMBERSHIP_SCOPE);
        await sbt.connect(admin).approveIdentityRoot(proofFixture.identityRoot);

        return {
            sbt,
            verifier,
            admin,
            member,
            otherMember,
            stranger,
            zkDeployer,
        };
    }

    function realMintArgs(overrides = {}) {
        return {
            pA: proofFixture.solidityProof.pA,
            pB: proofFixture.solidityProof.pB,
            pC: proofFixture.solidityProof.pC,
            nullifier: proofFixture.nullifierHash,
            root: proofFixture.identityRoot,
            ...overrides,
        };
    }

    describe("deployment and roles", function () {
        it("stores an immutable verifier/scope and grants separated admin roles", async function () {
            const {
                sbt,
                verifier,
                admin,
                ROOT_MANAGER_ROLE,
                PAUSER_ROLE,
                REVOKER_ROLE,
                DEFAULT_ADMIN_ROLE,
            } = await loadFixture(deployFixture);

            expect(await sbt.membershipVerifier()).to.equal(
                await verifier.getAddress()
            );
            const { chainId } = await ethers.provider.getNetwork();
            const encodedScopeDomain = ethers.AbiCoder.defaultAbiCoder().encode(
                ["bytes32", "uint256", "address"],
                [
                    await sbt.MEMBERSHIP_SCOPE_DOMAIN(),
                    chainId,
                    await sbt.getAddress(),
                ]
            );
            const expectedScope =
                (BigInt(ethers.keccak256(encodedScopeDomain)) %
                    (SNARK_SCALAR_FIELD - 1n)) +
                1n;
            expect(await sbt.membershipScope()).to.equal(expectedScope);
            expect(await sbt.membershipTokenURI()).to.equal(TOKEN_URI);
            expect(await sbt.hasRole(DEFAULT_ADMIN_ROLE, admin.address)).to.be.true;
            expect(await sbt.hasRole(ROOT_MANAGER_ROLE, admin.address)).to.be.true;
            expect(await sbt.hasRole(PAUSER_ROLE, admin.address)).to.be.true;
            expect(await sbt.hasRole(REVOKER_ROLE, admin.address)).to.be.true;
            expect(await sbt.paused()).to.be.false;
            expect(await sbt.totalSupply()).to.equal(0n);
            expect(await sbt.totalIssued()).to.equal(0n);
            expect(await sbt.REVOCATION_COOLDOWN()).to.equal(REVOCATION_COOLDOWN);
        });

        it("rejects invalid admin, verifier and metadata URI", async function () {
            const [admin] = await ethers.getSigners();
            const MockVerifier = await ethers.getContractFactory(
                "MockGroth16Verifier"
            );
            const verifier = await MockVerifier.deploy();
            const verifierAddress = await verifier.getAddress();
            const Factory = await ethers.getContractFactory("DAOCiudadanaSBT");

            await expect(
                Factory.deploy(
                    ethers.ZeroAddress,
                    verifierAddress,
                    TOKEN_URI
                )
            ).to.be.revertedWithCustomError(Factory, "InvalidAdmin");

            await expect(
                Factory.deploy(
                    admin.address,
                    admin.address,
                    TOKEN_URI
                )
            )
                .to.be.revertedWithCustomError(Factory, "InvalidVerifier")
                .withArgs(admin.address);

            await expect(
                Factory.deploy(
                    admin.address,
                    verifierAddress,
                    ""
                )
            ).to.be.revertedWithCustomError(
                Factory,
                "InvalidMembershipTokenURI"
            );
        });

        it("keeps root management separate from pause and revoke powers", async function () {
            const {
                sbt,
                admin,
                roleAccount,
                ROOT_MANAGER_ROLE,
                PAUSER_ROLE,
            } = await loadFixture(deployFixture);
            await sbt.connect(admin).grantRole(
                ROOT_MANAGER_ROLE,
                roleAccount.address
            );
            await sbt.connect(roleAccount).approveIdentityRoot(OTHER_ROOT);
            expect(await sbt.isIdentityRootApproved(OTHER_ROOT)).to.be.true;

            await expect(sbt.connect(roleAccount).pause("not allowed"))
                .to.be.revertedWithCustomError(
                    sbt,
                    "AccessControlUnauthorizedAccount"
                )
                .withArgs(roleAccount.address, PAUSER_ROLE);
        });

        it("supports ERC721 metadata and AccessControl interfaces", async function () {
            const { sbt } = await loadFixture(deployFixture);
            expect(await sbt.supportsInterface("0x80ac58cd")).to.be.true;
            expect(await sbt.supportsInterface("0x5b5e139f")).to.be.true;
            expect(await sbt.supportsInterface("0x49064906")).to.be.true;
            expect(await sbt.supportsInterface("0x7965db0b")).to.be.true;
            expect(await sbt.supportsInterface("0xffffffff")).to.be.false;
        });
    });

    describe("issuer roots", function () {
        it("allows only ROOT_MANAGER_ROLE to approve and revoke valid roots", async function () {
            const { sbt, stranger, ROOT_MANAGER_ROLE } = await loadFixture(
                deployFixture
            );

            await expect(sbt.connect(stranger).approveIdentityRoot(OTHER_ROOT))
                .to.be.revertedWithCustomError(
                    sbt,
                    "AccessControlUnauthorizedAccount"
                )
                .withArgs(stranger.address, ROOT_MANAGER_ROLE);

            await expect(sbt.approveIdentityRoot(OTHER_ROOT))
                .to.emit(sbt, "IdentityRootApproved");
            expect(await sbt.isIdentityRootApproved(OTHER_ROOT)).to.be.true;

            await expect(sbt.revokeIdentityRoot(OTHER_ROOT))
                .to.emit(sbt, "IdentityRootRevoked");
            expect(await sbt.isIdentityRootApproved(OTHER_ROOT)).to.be.false;
        });

        it("rejects zero/out-of-field roots and revoking unknown roots", async function () {
            const { sbt } = await loadFixture(deployFixture);
            for (const root of [0n, SNARK_SCALAR_FIELD]) {
                await expect(sbt.approveIdentityRoot(root))
                    .to.be.revertedWithCustomError(sbt, "InvalidIdentityRoot")
                    .withArgs(root);
            }
            await expect(sbt.revokeIdentityRoot(OTHER_ROOT))
                .to.be.revertedWithCustomError(
                    sbt,
                    "IdentityRootNotApproved"
                )
                .withArgs(OTHER_ROOT);
        });
    });

    describe("minting invariants", function () {
        it("lets any relayer submit a proof but binds every public signal internally", async function () {
            const { sbt, verifier, member, stranger } = await loadFixture(
                deployFixture
            );
            await verifier.setExpectedPublicSignals(
                [
                    ROOT,
                    BigInt(NULLIFIER),
                    BigInt(member.address),
                    await sbt.membershipScope(),
                ],
                true
            );

            expect(
                await sbt
                    .connect(stranger)
                    .mintMembership.staticCall(
                        member.address,
                        P_A,
                        P_B,
                        P_C,
                        NULLIFIER,
                        ROOT
                    )
            ).to.equal(1n);

            const tx = await mint(sbt, member.address, { caller: stranger });
            const block = await ethers.provider.getBlock(tx.blockNumber);
            await expect(tx)
                .to.emit(sbt, "MembershipMinted")
                .withArgs(
                    member.address,
                    1n,
                    NULLIFIER,
                    ROOT,
                    block.timestamp
                );

            expect(await sbt.ownerOf(1n)).to.equal(member.address);
            expect(await sbt.getNullifierHash(1n)).to.equal(NULLIFIER);
            expect(await sbt.getIdentityRoot(1n)).to.equal(ROOT);
            expect(await sbt.isNullifierUsed(NULLIFIER)).to.be.true;
            expect(await sbt.tokenURI(1n)).to.equal(TOKEN_URI);
        });

        it("rejects a proof whose verifier returns false or reverts", async function () {
            const { sbt, verifier, member } = await loadFixture(deployFixture);
            await verifier.configure(false, false);
            await expect(mint(sbt, member.address)).to.be.revertedWithCustomError(
                sbt,
                "InvalidMembershipProof"
            );

            await verifier.configure(true, true);
            await expect(mint(sbt, member.address)).to.be.revertedWithCustomError(
                sbt,
                "InvalidMembershipProof"
            );
        });

        it("rejects zero recipient, unknown/revoked root and invalid nullifier", async function () {
            const { sbt, member } = await loadFixture(deployFixture);
            await expect(mint(sbt, ethers.ZeroAddress))
                .to.be.revertedWithCustomError(sbt, "InvalidRecipient");

            await expect(mint(sbt, member.address, { root: OTHER_ROOT }))
                .to.be.revertedWithCustomError(
                    sbt,
                    "IdentityRootNotApproved"
                )
                .withArgs(OTHER_ROOT);

            await sbt.revokeIdentityRoot(ROOT);
            await expect(mint(sbt, member.address))
                .to.be.revertedWithCustomError(
                    sbt,
                    "IdentityRootNotApproved"
                )
                .withArgs(ROOT);

            await sbt.approveIdentityRoot(ROOT);
            for (const value of [0n, SNARK_SCALAR_FIELD]) {
                const nullifier = ethers.zeroPadValue(
                    ethers.toBeHex(value),
                    32
                );
                await expect(mint(sbt, member.address, { nullifier }))
                    .to.be.revertedWithCustomError(
                        sbt,
                        "InvalidNullifierHash"
                    )
                    .withArgs(nullifier);
            }
        });

        it("prevents wallet duplication and permanent nullifier replay", async function () {
            const { sbt, member, otherMember } = await loadFixture(
                deployMintedFixture
            );

            await expect(
                mint(sbt, member.address, { nullifier: OTHER_NULLIFIER })
            )
                .to.be.revertedWithCustomError(sbt, "AlreadyHasMembership")
                .withArgs(member.address);

            await expect(mint(sbt, otherMember.address))
                .to.be.revertedWithCustomError(sbt, "NullifierAlreadyUsed")
                .withArgs(NULLIFIER);
        });

        it("updates membership and nullifier before the ERC721 receiver callback", async function () {
            const { sbt, verifier } = await loadFixture(deployFixture);
            const Probe = await ethers.getContractFactory("ReceiverProbe");
            const probe = await Probe.deploy();
            const probeAddress = await probe.getAddress();
            await probe.setExpectedNullifier(NULLIFIER);
            await verifier.setExpectedPublicSignals(
                [
                    ROOT,
                    BigInt(NULLIFIER),
                    BigInt(probeAddress),
                    await sbt.membershipScope(),
                ],
                true
            );

            await mint(sbt, probeAddress);
            expect(await probe.sawMembershipDuringCallback()).to.be.true;
            expect(await probe.sawNullifierUsedDuringCallback()).to.be.true;
            expect(await probe.tokenIdDuringCallback()).to.equal(1n);
        });
    });

    describe("real Groth16 integration", function () {
        it("accepts the generated proof through an arbitrary relayer", async function () {
            const { sbt, member, stranger } = await loadFixture(
                deployRealVerifierFixture
            );
            await expect(
                mint(sbt, member.address, {
                    caller: stranger,
                    ...realMintArgs(),
                })
            ).to.emit(sbt, "MembershipMinted");
            expect(await sbt.ownerOf(1n)).to.equal(member.address);
        });

        it("cannot redirect the proof to a different recipient", async function () {
            const { sbt, otherMember, stranger } = await loadFixture(
                deployRealVerifierFixture
            );
            await expect(
                mint(sbt, otherMember.address, {
                    caller: stranger,
                    ...realMintArgs(),
                })
            ).to.be.revertedWithCustomError(sbt, "InvalidMembershipProof");
        });

        it("invalidates changes to root, scope or proof points", async function () {
            const { sbt, verifier, admin, member, zkDeployer } =
                await loadFixture(deployRealVerifierFixture);

            const alteredRoot = BigInt(proofFixture.identityRoot) + 1n;
            await sbt.connect(admin).approveIdentityRoot(alteredRoot);
            await expect(
                mint(sbt, member.address, realMintArgs({ root: alteredRoot }))
            ).to.be.revertedWithCustomError(sbt, "InvalidMembershipProof");

            const Factory = await ethers.getContractFactory(
                "DAOCiudadanaSBT",
                zkDeployer
            );
            const otherDeployment = await Factory.deploy(
                admin.address,
                await verifier.getAddress(),
                TOKEN_URI
            );
            await otherDeployment.waitForDeployment();
            expect(await otherDeployment.membershipScope()).not.to.equal(
                MEMBERSHIP_SCOPE
            );
            await otherDeployment
                .connect(admin)
                .approveIdentityRoot(proofFixture.identityRoot);
            await expect(
                mint(otherDeployment, member.address, realMintArgs())
            ).to.be.revertedWithCustomError(
                otherDeployment,
                "InvalidMembershipProof"
            );

            const alteredA = [...proofFixture.solidityProof.pA];
            alteredA[0] = (BigInt(alteredA[0]) + 1n).toString();
            await expect(
                mint(sbt, member.address, realMintArgs({ pA: alteredA }))
            ).to.be.revertedWithCustomError(sbt, "InvalidMembershipProof");
        });

        it("keeps the real nullifier consumed after a successful proof", async function () {
            const { sbt, member, otherMember } = await loadFixture(
                deployRealVerifierFixture
            );
            await mint(sbt, member.address, realMintArgs());
            await expect(mint(sbt, otherMember.address, realMintArgs()))
                .to.be.revertedWithCustomError(sbt, "NullifierAlreadyUsed")
                .withArgs(proofFixture.nullifierHash);
        });
    });

    describe("soulbound, pause and revocation", function () {
        it("rejects transfers, including transfers by an approved operator", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(
                deployMintedFixture
            );
            await expect(
                sbt
                    .connect(member)
                    .transferFrom(member.address, otherMember.address, tokenId)
            ).to.be.revertedWithCustomError(
                sbt,
                "SoulboundTokenCannotBeTransferred"
            );

            await sbt.connect(member).approve(otherMember.address, tokenId);
            await expect(
                sbt
                    .connect(otherMember)
                    .transferFrom(member.address, otherMember.address, tokenId)
            ).to.be.revertedWithCustomError(
                sbt,
                "SoulboundTokenCannotBeTransferred"
            );
        });

        it("lets only PAUSER_ROLE pause and blocks mint while paused", async function () {
            const { sbt, member, stranger, PAUSER_ROLE } = await loadFixture(
                deployFixture
            );
            await expect(sbt.connect(stranger).pause("attack"))
                .to.be.revertedWithCustomError(
                    sbt,
                    "AccessControlUnauthorizedAccount"
                )
                .withArgs(stranger.address, PAUSER_ROLE);

            await expect(sbt.pause("incident")).to.emit(sbt, "ContractPaused");
            await expect(mint(sbt, member.address)).to.be.revertedWithCustomError(
                sbt,
                "EnforcedPause"
            );
            await expect(sbt.unpause()).to.emit(sbt, "ContractUnpaused");
            await expect(mint(sbt, member.address)).to.emit(
                sbt,
                "MembershipMinted"
            );
        });

        it("enforces the revocation role and three-day cooldown", async function () {
            const { sbt, stranger, tokenId, REVOKER_ROLE } = await loadFixture(
                deployMintedFixture
            );
            await expect(sbt.connect(stranger).requestRevocation(tokenId))
                .to.be.revertedWithCustomError(
                    sbt,
                    "AccessControlUnauthorizedAccount"
                )
                .withArgs(stranger.address, REVOKER_ROLE);

            await expect(sbt.executeRevocation(tokenId, "too early"))
                .to.be.revertedWithCustomError(sbt, "RevocationNotRequested")
                .withArgs(tokenId);
            await sbt.requestRevocation(tokenId);
            await expect(sbt.executeRevocation(tokenId, "too early"))
                .to.be.revertedWithCustomError(
                    sbt,
                    "RevocationCooldownNotPassed"
                );
        });

        it("burns after cooldown but never frees the identity nullifier", async function () {
            const { sbt, member, otherMember, tokenId } = await loadFixture(
                deployMintedFixture
            );
            await sbt.requestRevocation(tokenId);
            await time.increase(REVOCATION_COOLDOWN + 1);
            await expect(sbt.executeRevocation(tokenId, "eligibility revoked"))
                .to.emit(sbt, "MembershipRevoked")
                .withArgs(member.address, tokenId, "eligibility revoked");

            expect(await sbt.hasMembership(member.address)).to.be.false;
            expect(await sbt.getMembershipToken(member.address)).to.equal(0n);
            expect(await sbt.isNullifierUsed(NULLIFIER)).to.be.true;
            expect(await sbt.totalSupply()).to.equal(0n);
            expect(await sbt.totalIssued()).to.equal(1n);
            await expect(sbt.getNullifierHash(tokenId))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist")
                .withArgs(tokenId);

            await expect(mint(sbt, otherMember.address))
                .to.be.revertedWithCustomError(sbt, "NullifierAlreadyUsed")
                .withArgs(NULLIFIER);
        });

        it("can cancel a pending revocation", async function () {
            const { sbt, member, tokenId } = await loadFixture(
                deployMintedFixture
            );
            await sbt.requestRevocation(tokenId);
            await expect(sbt.cancelRevocation(tokenId))
                .to.emit(sbt, "RevocationCancelled")
                .withArgs(member.address, tokenId);
            const [requested, executeAfter] = await sbt.getRevocationStatus(
                tokenId
            );
            expect(requested).to.be.false;
            expect(executeAfter).to.equal(0n);
        });
    });

    describe("empty views", function () {
        it("returns defaults for unused identities and reverts per-token views", async function () {
            const { sbt, stranger } = await loadFixture(deployFixture);
            expect(await sbt.hasMembership(stranger.address)).to.be.false;
            expect(await sbt.getMembershipToken(stranger.address)).to.equal(0n);
            expect(await sbt.isNullifierUsed(OTHER_NULLIFIER)).to.be.false;
            await expect(sbt.getNullifierHash(42n))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist")
                .withArgs(42n);
            await expect(sbt.getIdentityRoot(42n))
                .to.be.revertedWithCustomError(sbt, "TokenDoesNotExist")
                .withArgs(42n);
        });
    });
});
