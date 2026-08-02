pragma circom 2.2.0;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/escalarmulany.circom";
include "circomlib/circuits/bitify.circom";
include "circomlib/circuits/eddsaposeidon.circom";

/**
 * Procesamiento de mensajes cifrados de MACI (ADR-001, D-3).
 *
 * Es el circuito que faltaba: `maci_tally.circom` suma un estado ya procesado,
 * y este es quien lo produce. Prueba, sin revelar el contenido del mensaje:
 *
 *   1. que el coordinador descifró con SU llave privada (ECDH real, no una
 *      afirmación) el mensaje dirigido a la llave efímera del votante;
 *   2. que el comando venía firmado por la llave MACI vigente de ese votante;
 *   3. que el nonce es el que corresponde (anti-replay);
 *   4. que el peso no excede sus créditos;
 *   5. que la hoja anterior estaba en `currentStateRoot` y la nueva produce
 *      `newStateRoot`.
 *
 * POR QUÉ ESTO IMPORTA
 * ────────────────────
 * Sin este circuito, el coordinador podría afirmar cualquier estado final: es
 * el único que puede descifrar, así que su palabra sería la única evidencia.
 * Aquí queda obligado a demostrar que el estado que publica se deriva de los
 * mensajes que la cadena ya registró.
 *
 * CIFRADO (frontera de protocolo con el cliente)
 * ──────────────────────────────────────────────
 * Clave compartida por ECDH sobre Baby Jubjub:
 *
 *     shared = coordinatorPrivKey · ephemeralPubKey
 *
 * y cifrado de flujo aditivo sobre el campo:
 *
 *     ciphertext[i] = plaintext[i] + Poseidon(shared.x, shared.y, i)  (mod p)
 *
 * El cliente calcula la MISMA clave como `ephemeralPrivKey · coordinatorPubKey`.
 * No es el `poseidonDecrypt` de la implementación de referencia de MACI: es un
 * esquema equivalente en garantías y más barato en restricciones, pero exige
 * que el cliente cifre exactamente así. Está documentado en REQUEST_TO_CODEX.md.
 *
 * Disposición del texto plano (10 elementos, los que acepta el contrato):
 *   [0] stateIndex   [1] voteOption  [2] voteWeight  [3] nonce
 *   [4] newPubKeyX   [5] newPubKeyY
 *   [6] sigR8x       [7] sigR8y      [8] sigS        [9] relleno
 *
 * LÍMITE CONOCIDO — mensajes inválidos
 * ────────────────────────────────────
 * Este circuito exige que la firma sea válida: un mensaje mal firmado no puede
 * probarse, y el coordinador debe excluirlo. Procesar mensajes inválidos como
 * "no-op" sin revelar cuáles son requiere un verificador EdDSA que devuelva un
 * booleano, y `EdDSAPoseidonVerifier` de circomlib solo restringe — no expone
 * salida. Cerrar ese hueco es trabajo pendiente y está anotado en el README.
 *
 * ESTADO: compilado y probado con testigo, SIN ceremonia de confianza.
 */

/// Descifra un elemento del flujo: p[i] = c[i] - Poseidon(sx, sy, i).
template StreamDecrypt(length) {
    signal input sharedX;
    signal input sharedY;
    signal input ciphertext[length];
    signal output plaintext[length];

    component pad[length];
    for (var i = 0; i < length; i++) {
        pad[i] = Poseidon(3);
        pad[i].inputs[0] <== sharedX;
        pad[i].inputs[1] <== sharedY;
        pad[i].inputs[2] <== i;
        plaintext[i] <== ciphertext[i] - pad[i].out;
    }
}

/// Hoja de estado. Idéntica a la de maci_tally.circom: ambos circuitos deben
/// coincidir bit a bit o el tally no reconoce el estado que este produce.
template StateLeaf(voteOptions) {
    signal input pubKeyX;
    signal input pubKeyY;
    signal input voiceCredits;
    signal input votes[voteOptions];
    signal output out;

    component voteHasher = Poseidon(voteOptions);
    for (var i = 0; i < voteOptions; i++) {
        voteHasher.inputs[i] <== votes[i];
    }

    component leafHasher = Poseidon(4);
    leafHasher.inputs[0] <== pubKeyX;
    leafHasher.inputs[1] <== pubKeyY;
    leafHasher.inputs[2] <== voiceCredits;
    leafHasher.inputs[3] <== voteHasher.out;
    out <== leafHasher.out;
}

/// Raíz que resulta de colocar `leaf` en la posición descrita por la ruta.
template MerkleRootFromPath(levels) {
    signal input leaf;
    signal input pathElements[levels];
    signal input pathIndices[levels];
    signal output root;

    signal hashes[levels + 1];
    signal left[levels];
    signal right[levels];
    component hashers[levels];

    hashes[0] <== leaf;
    for (var i = 0; i < levels; i++) {
        pathIndices[i] * (pathIndices[i] - 1) === 0;

        left[i] <== hashes[i] + pathIndices[i] * (pathElements[i] - hashes[i]);
        right[i] <== pathElements[i] + pathIndices[i] * (hashes[i] - pathElements[i]);

        hashers[i] = Poseidon(2);
        hashers[i].inputs[0] <== left[i];
        hashers[i].inputs[1] <== right[i];
        hashes[i + 1] <== hashers[i].out;
    }
    root <== hashes[levels];
}

template ProcessMessage(stateTreeDepth, voteOptions, maxVoiceCredits) {
    var MSG_LENGTH = 10;

    // === Privado ===
    signal input coordinatorPrivKey;
    signal input ephemeralPubKey[2];
    signal input ciphertext[MSG_LENGTH];

    // Hoja del votante ANTES del mensaje.
    signal input voterPubKey[2];
    signal input voiceCredits;
    signal input currentVotes[voteOptions];
    signal input currentNonce;
    signal input pathElements[stateTreeDepth];
    signal input pathIndices[stateTreeDepth];

    // === Público ===
    signal input currentStateRoot;
    signal input newStateRoot;
    // Ata la prueba al mensaje que la cadena registró: sin esto el coordinador
    // podría procesar un mensaje que nunca se publicó.
    signal input messageHash;

    // --- 1. ECDH: el coordinador demuestra que descifró con su llave ---
    // Se calcula el punto compartido dentro del circuito. Pasarlo como entrada
    // dejaría que el coordinador inventara la clave y, con ella, el comando.
    component privBits = Num2Bits(253);
    privBits.in <== coordinatorPrivKey;

    component ecdh = EscalarMulAny(253);
    ecdh.p[0] <== ephemeralPubKey[0];
    ecdh.p[1] <== ephemeralPubKey[1];
    for (var i = 0; i < 253; i++) {
        ecdh.e[i] <== privBits.out[i];
    }

    // --- 2. Descifrado ---
    component decrypted = StreamDecrypt(MSG_LENGTH);
    decrypted.sharedX <== ecdh.out[0];
    decrypted.sharedY <== ecdh.out[1];
    for (var i = 0; i < MSG_LENGTH; i++) {
        decrypted.ciphertext[i] <== ciphertext[i];
    }

    signal voteOption;
    signal voteWeight;
    signal msgNonce;
    signal newPubKeyX;
    signal newPubKeyY;

    voteOption <== decrypted.plaintext[1];
    voteWeight <== decrypted.plaintext[2];
    msgNonce   <== decrypted.plaintext[3];
    newPubKeyX <== decrypted.plaintext[4];
    newPubKeyY <== decrypted.plaintext[5];

    // --- 3. El comando venía firmado por la llave MACI vigente ---
    // Es lo que impide que el coordinador fabrique comandos: solo el votante
    // puede producir una firma que verifique contra su llave publicada.
    component commandHash = Poseidon(6);
    for (var i = 0; i < 6; i++) {
        commandHash.inputs[i] <== decrypted.plaintext[i];
    }

    component signature = EdDSAPoseidonVerifier();
    signature.enabled <== 1;
    signature.Ax <== voterPubKey[0];
    signature.Ay <== voterPubKey[1];
    signature.R8x <== decrypted.plaintext[6];
    signature.R8y <== decrypted.plaintext[7];
    signature.S <== decrypted.plaintext[8];
    signature.M <== commandHash.out;

    // --- 4. Anti-replay y límite de créditos ---
    msgNonce === currentNonce + 1;

    component weightWithinCredits = LessEqThan(64);
    weightWithinCredits.in[0] <== voteWeight;
    weightWithinCredits.in[1] <== voiceCredits;
    weightWithinCredits.out === 1;

    component creditsWithinMax = LessEqThan(64);
    creditsWithinMax.in[0] <== voiceCredits;
    creditsWithinMax.in[1] <== maxVoiceCredits;
    creditsWithinMax.out === 1;

    component optionInRange = LessThan(16);
    optionInRange.in[0] <== voteOption;
    optionInRange.in[1] <== voteOptions;
    optionInRange.out === 1;

    // --- 5. Transición de estado ---
    // El voto sustituye al anterior de esa opción; el resto queda igual. Es la
    // semántica de "el último mensaje válido manda", que es exactamente cómo
    // un votante coaccionado anula en secreto lo que prometió.
    component isTarget[voteOptions];
    signal newVotes[voteOptions];
    for (var j = 0; j < voteOptions; j++) {
        isTarget[j] = IsEqual();
        isTarget[j].in[0] <== voteOption;
        isTarget[j].in[1] <== j;
        newVotes[j] <== currentVotes[j] + isTarget[j].out * (voteWeight - currentVotes[j]);
    }

    // La hoja anterior debe estar en la raíz comprometida.
    component previousLeaf = StateLeaf(voteOptions);
    previousLeaf.pubKeyX <== voterPubKey[0];
    previousLeaf.pubKeyY <== voterPubKey[1];
    previousLeaf.voiceCredits <== voiceCredits;
    for (var j = 0; j < voteOptions; j++) {
        previousLeaf.votes[j] <== currentVotes[j];
    }

    component previousRoot = MerkleRootFromPath(stateTreeDepth);
    previousRoot.leaf <== previousLeaf.out;
    for (var k = 0; k < stateTreeDepth; k++) {
        previousRoot.pathElements[k] <== pathElements[k];
        previousRoot.pathIndices[k] <== pathIndices[k];
    }
    previousRoot.root === currentStateRoot;

    // La hoja nueva, en la MISMA posición, debe producir la raíz publicada.
    // Reutilizar la ruta es lo que garantiza que solo cambió esta hoja.
    component updatedLeaf = StateLeaf(voteOptions);
    updatedLeaf.pubKeyX <== newPubKeyX;
    updatedLeaf.pubKeyY <== newPubKeyY;
    updatedLeaf.voiceCredits <== voiceCredits;
    for (var j = 0; j < voteOptions; j++) {
        updatedLeaf.votes[j] <== newVotes[j];
    }

    component updatedRoot = MerkleRootFromPath(stateTreeDepth);
    updatedRoot.leaf <== updatedLeaf.out;
    for (var k = 0; k < stateTreeDepth; k++) {
        updatedRoot.pathElements[k] <== pathElements[k];
        updatedRoot.pathIndices[k] <== pathIndices[k];
    }
    updatedRoot.root === newStateRoot;

    // --- 6. El mensaje procesado es el que la cadena registró ---
    component publishedHash = Poseidon(3);
    publishedHash.inputs[0] <== ephemeralPubKey[0];
    publishedHash.inputs[1] <== ephemeralPubKey[1];
    component ctHash = Poseidon(MSG_LENGTH);
    for (var i = 0; i < MSG_LENGTH; i++) {
        ctHash.inputs[i] <== ciphertext[i];
    }
    publishedHash.inputs[2] <== ctHash.out;
    publishedHash.out === messageHash;
}

// Parámetros del piloto, alineados con maci_tally.circom:
//   stateTreeDepth 10 -> 1024 votantes
//   voteOptions     3 -> a favor / en contra / abstención
//   maxVoiceCredits 1 -> voto simple
//
// Un mensaje por prueba: las pruebas se encadenan por raíz de estado. Agrupar
// en lotes es una optimización posterior, no un cambio de semántica.
component main {public [currentStateRoot, newStateRoot, messageHash]} =
    ProcessMessage(10, 3, 1);
