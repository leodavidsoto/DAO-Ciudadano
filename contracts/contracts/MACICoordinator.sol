// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./interfaces/ITallyVerifier.sol";

interface IMembershipRegistry {
    function hasMembership(address member) external view returns (bool);
}

/**
 * @title MACICoordinator
 * @notice Registro de inscripciones y mensajes cifrados para gobernanza
 *         incoercible (ADR-001, D-3).
 *
 * Qué problema resuelve MACI
 * ──────────────────────────
 * Un voto firmado y verificable públicamente se puede vender: el comprador
 * exige la firma como recibo. MACI lo impide cifrando la papeleta hacia el
 * coordinador y permitiendo **cambiar de llave**. Quien es coaccionado envía
 * después un mensaje con una llave nueva que invalida el anterior, y el
 * coaccionador no puede distinguir un voto vigente de uno ya anulado.
 *
 * Qué hace este contrato
 * ──────────────────────
 *  - Inscribe votantes que acrediten membresía en el SBT.
 *  - Acumula mensajes cifrados en una cadena de hashes, fijando su contenido
 *    y su ORDEN. El orden es esencial: en MACI el último mensaje válido de
 *    una llave es el que cuenta.
 *  - Recibe del coordinador el resultado con una prueba Groth16 y lo publica
 *    solo si el verificador la acepta.
 *
 * Qué NO hace, y por qué se dice explícito
 * ────────────────────────────────────────
 *  - No descifra nada: es imposible on-chain, y ese es justamente el punto.
 *  - No comprueba que el resultado publicado corresponda a los mensajes
 *    acumulados más allá de lo que afirme el circuito de tally. Ese circuito
 *    NO existe todavía en este repositorio.
 *
 * Por eso `tallyVerifier` puede ser address(0) al desplegar, y en ese estado
 * `publishTally` revierte. Un coordinador no puede publicar un resultado sin
 * prueba: sería exactamente el recuento no verificable que MACI existe para
 * eliminar.
 *
 * Se usa una cadena de hashes y no un árbol Merkle incremental porque acá
 * solo hace falta comprometerse con la secuencia de mensajes; el árbol que el
 * circuito de tally necesitará se reconstruye off-chain a partir de los
 * eventos, que llevan todos los datos.
 */
contract MACICoordinator is AccessControl, Pausable, ReentrancyGuard {
    uint256 public constant SNARK_SCALAR_FIELD =
        21888242871839275222246405745257275088548364400416034343698204186575808495617;

    bytes32 public constant COORDINATOR_ROLE = keccak256("COORDINATOR_ROLE");
    bytes32 public constant POLL_MANAGER_ROLE = keccak256("POLL_MANAGER_ROLE");

    IMembershipRegistry public immutable membership;

    /// Verificador del circuito de tally. Sustituible: el circuito todavía no
    /// existe y su ceremonia de confianza cambiará el verificador.
    ITallyVerifier public tallyVerifier;

    /// Llave pública Baby Jubjub del coordinador. Los votantes cifran hacia
    /// ella; sin una llave publicada no se puede votar.
    uint256 public coordinatorPubKeyX;
    uint256 public coordinatorPubKeyY;

    struct Poll {
        uint256 signUpDeadline;
        uint256 votingDeadline;
        uint256 signUpCount;
        uint256 messageCount;
        bytes32 messageChain;
        bool tallied;
        bytes32 tallyCommitment;
    }

    uint256 public pollCount;
    mapping(uint256 => Poll) private _polls;
    /// pollId => votante => inscrito. Una inscripción por miembro y consulta.
    mapping(uint256 => mapping(address => bool)) private _signedUp;

    event PollCreated(
        uint256 indexed pollId,
        uint256 signUpDeadline,
        uint256 votingDeadline
    );
    event SignedUp(
        uint256 indexed pollId,
        address indexed voter,
        uint256 pubKeyX,
        uint256 pubKeyY,
        uint256 index
    );
    event MessagePublished(
        uint256 indexed pollId,
        uint256 indexed index,
        uint256 ephemeralPubKeyX,
        uint256 ephemeralPubKeyY,
        uint256[10] ciphertext,
        bytes32 messageChain
    );
    event TallyPublished(
        uint256 indexed pollId,
        bytes32 tallyCommitment,
        address indexed by
    );
    event CoordinatorKeyUpdated(uint256 pubKeyX, uint256 pubKeyY);
    event TallyVerifierUpdated(address indexed previous, address indexed current);

    error InvalidAdmin();
    error InvalidMembershipRegistry();
    error InvalidCoordinatorKey();
    error InvalidDeadlines();
    error PollDoesNotExist(uint256 pollId);
    error SignUpClosed(uint256 pollId);
    error VotingClosed(uint256 pollId);
    error NotAMember(address voter);
    error AlreadySignedUp(uint256 pollId, address voter);
    error NotSignedUp(uint256 pollId, address voter);
    error InvalidPublicKey();
    error InvalidCiphertext();
    error TallyVerifierNotConfigured();
    error InvalidTallyProof();
    error AlreadyTallied(uint256 pollId);
    error VotingStillOpen(uint256 pollId);

    /**
     * @param admin Multisig que recibe la administración y los roles.
     * @param membershipRegistry Contrato SBT que acredita membresía.
     * @param tallyVerifier_ Verificador del circuito de tally. Puede ser
     * address(0) mientras el circuito no exista: en ese estado publishTally
     * revierte en vez de aceptar un resultado sin prueba.
     */
    constructor(
        address admin,
        address membershipRegistry,
        address tallyVerifier_
    ) {
        if (admin == address(0)) revert InvalidAdmin();
        if (membershipRegistry.code.length == 0) revert InvalidMembershipRegistry();

        membership = IMembershipRegistry(membershipRegistry);
        tallyVerifier = ITallyVerifier(tallyVerifier_);

        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(COORDINATOR_ROLE, admin);
        _grantRole(POLL_MANAGER_ROLE, admin);
    }

    // === Administración ===

    /**
     * @dev Publica la llave pública del coordinador (punto de Baby Jubjub).
     *
     * No se valida la ecuación de curva on-chain a propósito: costaría gas en
     * cada despliegue para comprobar algo que solo el coordinador se
     * perjudica a sí mismo por equivocar (nadie podría cifrarle nada legible).
     * La validación real vive en el backend, que sí la hace antes de aceptar
     * llaves de votantes.
     */
    function setCoordinatorPubKey(
        uint256 x,
        uint256 y
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        if (x >= SNARK_SCALAR_FIELD || y >= SNARK_SCALAR_FIELD) {
            revert InvalidCoordinatorKey();
        }
        if (x == 0 && y == 1) revert InvalidCoordinatorKey(); // punto identidad
        coordinatorPubKeyX = x;
        coordinatorPubKeyY = y;
        emit CoordinatorKeyUpdated(x, y);
    }

    function setTallyVerifier(
        address verifier
    ) external onlyRole(DEFAULT_ADMIN_ROLE) {
        address previous = address(tallyVerifier);
        tallyVerifier = ITallyVerifier(verifier);
        emit TallyVerifierUpdated(previous, verifier);
    }

    function pause(string calldata) external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    // === Ciclo de la consulta ===

    function createPoll(
        uint256 signUpDuration,
        uint256 votingDuration
    ) external onlyRole(POLL_MANAGER_ROLE) whenNotPaused returns (uint256) {
        if (signUpDuration == 0 || votingDuration == 0) revert InvalidDeadlines();
        if (coordinatorPubKeyX == 0 && coordinatorPubKeyY == 0) {
            // Sin llave del coordinador nadie puede cifrar: abrir la consulta
            // solo produciría votos ilegibles.
            revert InvalidCoordinatorKey();
        }

        uint256 pollId = ++pollCount;
        uint256 signUpDeadline = block.timestamp + signUpDuration;
        uint256 votingDeadline = signUpDeadline + votingDuration;

        _polls[pollId] = Poll({
            signUpDeadline: signUpDeadline,
            votingDeadline: votingDeadline,
            signUpCount: 0,
            messageCount: 0,
            messageChain: bytes32(0),
            tallied: false,
            tallyCommitment: bytes32(0)
        });

        emit PollCreated(pollId, signUpDeadline, votingDeadline);
        return pollId;
    }

    /**
     * @dev Inscribe al llamante y publica su llave MACI inicial.
     *
     * Se exige membresía SBT: sin ese filtro cualquier dirección inflaría el
     * censo, que es precisamente el Sybil que el SBT existe para impedir.
     */
    function signUp(
        uint256 pollId,
        uint256 pubKeyX,
        uint256 pubKeyY
    ) external whenNotPaused nonReentrant {
        Poll storage poll = _requirePoll(pollId);
        if (block.timestamp >= poll.signUpDeadline) revert SignUpClosed(pollId);
        if (!membership.hasMembership(msg.sender)) revert NotAMember(msg.sender);
        if (_signedUp[pollId][msg.sender]) revert AlreadySignedUp(pollId, msg.sender);
        if (pubKeyX >= SNARK_SCALAR_FIELD || pubKeyY >= SNARK_SCALAR_FIELD) {
            revert InvalidPublicKey();
        }
        if (pubKeyX == 0 && pubKeyY == 1) revert InvalidPublicKey();

        _signedUp[pollId][msg.sender] = true;
        uint256 index = poll.signUpCount++;

        emit SignedUp(pollId, msg.sender, pubKeyX, pubKeyY, index);
    }

    /**
     * @dev Publica un mensaje cifrado (voto o cambio de llave).
     *
     * El contrato NO puede distinguir un voto de un cambio de llave: ambos son
     * texto cifrado indistinguible. Esa indistinguibilidad es la propiedad que
     * hace incoercible al sistema, no una limitación.
     *
     * El acumulador encadena el hash anterior con el mensaje, así que fija
     * contenido y orden. El orden decide: en MACI vale el último mensaje
     * válido de cada llave.
     */
    function publishMessage(
        uint256 pollId,
        uint256 ephemeralPubKeyX,
        uint256 ephemeralPubKeyY,
        uint256[10] calldata ciphertext
    ) external whenNotPaused nonReentrant {
        Poll storage poll = _requirePoll(pollId);
        if (block.timestamp >= poll.votingDeadline) revert VotingClosed(pollId);
        // Solo inscritos: aceptar mensajes de cualquiera obligaría al
        // coordinador a descifrar basura y abriría un vector de spam gratuito.
        if (!_signedUp[pollId][msg.sender]) revert NotSignedUp(pollId, msg.sender);
        if (
            ephemeralPubKeyX >= SNARK_SCALAR_FIELD ||
            ephemeralPubKeyY >= SNARK_SCALAR_FIELD
        ) {
            revert InvalidPublicKey();
        }

        for (uint256 i = 0; i < ciphertext.length; i++) {
            if (ciphertext[i] >= SNARK_SCALAR_FIELD) revert InvalidCiphertext();
        }

        uint256 index = poll.messageCount++;
        poll.messageChain = keccak256(
            abi.encode(
                poll.messageChain,
                ephemeralPubKeyX,
                ephemeralPubKeyY,
                ciphertext
            )
        );

        emit MessagePublished(
            pollId,
            index,
            ephemeralPubKeyX,
            ephemeralPubKeyY,
            ciphertext,
            poll.messageChain
        );
    }

    /**
     * @dev Publica el resultado con su prueba. Sin verificador, revierte.
     *
     * Las señales públicas atan la prueba a esta consulta: el acumulador de
     * mensajes, el número de inscritos y el compromiso del resultado. Sin esa
     * atadura, una prueba de otra consulta serviría para publicar aquí.
     */
    function publishTally(
        uint256 pollId,
        uint256[2] calldata pA,
        uint256[2][2] calldata pB,
        uint256[2] calldata pC,
        bytes32 tallyCommitment
    ) external onlyRole(COORDINATOR_ROLE) whenNotPaused nonReentrant {
        Poll storage poll = _requirePoll(pollId);
        if (block.timestamp < poll.votingDeadline) revert VotingStillOpen(pollId);
        if (poll.tallied) revert AlreadyTallied(pollId);
        if (address(tallyVerifier) == address(0)) {
            revert TallyVerifierNotConfigured();
        }

        uint256[3] memory publicSignals = [
            uint256(poll.messageChain) % SNARK_SCALAR_FIELD,
            poll.signUpCount,
            uint256(tallyCommitment) % SNARK_SCALAR_FIELD
        ];

        if (!tallyVerifier.verifyProof(pA, pB, pC, publicSignals)) {
            revert InvalidTallyProof();
        }

        poll.tallied = true;
        poll.tallyCommitment = tallyCommitment;

        emit TallyPublished(pollId, tallyCommitment, msg.sender);
    }

    // === Vistas ===

    function getPoll(
        uint256 pollId
    )
        external
        view
        returns (
            uint256 signUpDeadline,
            uint256 votingDeadline,
            uint256 signUpCount,
            uint256 messageCount,
            bytes32 messageChain,
            bool tallied,
            bytes32 tallyCommitment
        )
    {
        Poll storage poll = _requirePollView(pollId);
        return (
            poll.signUpDeadline,
            poll.votingDeadline,
            poll.signUpCount,
            poll.messageCount,
            poll.messageChain,
            poll.tallied,
            poll.tallyCommitment
        );
    }

    function isSignedUp(uint256 pollId, address voter) external view returns (bool) {
        return _signedUp[pollId][voter];
    }

    function tallyIsVerifiable() external view returns (bool) {
        return address(tallyVerifier) != address(0);
    }

    function _requirePoll(uint256 pollId) private view returns (Poll storage) {
        if (pollId == 0 || pollId > pollCount) revert PollDoesNotExist(pollId);
        return _polls[pollId];
    }

    function _requirePollView(uint256 pollId) private view returns (Poll storage) {
        return _requirePoll(pollId);
    }
}
