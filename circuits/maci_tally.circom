pragma circom 2.2.0;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";

/**
 * Recuento verificable de MACI (ADR-001, D-3).
 *
 * DÓNDE ENCAJA ESTE CIRCUITO
 * ──────────────────────────
 * MACI necesita DOS circuitos, y este es el segundo:
 *
 *   1. processMessages — descifra los mensajes con la llave del coordinador,
 *      aplica los comandos (voto y cambio de llave) en orden y produce el
 *      estado final: cuánto peso asignó cada votante a cada opción.
 *      **NO existe todavía en este repositorio.**
 *
 *   2. maci_tally (este) — dado ese estado, prueba que los totales publicados
 *      son exactamente la suma de las hojas, sin revelar ninguna hoja.
 *
 * Separarlos es lo que hace MACI en producción y no es un atajo: descifrar y
 * recorrer el historial de comandos cuesta órdenes de magnitud más
 * restricciones que sumar, y mezclarlo todo produce un circuito que no cabe
 * en una ceremonia razonable.
 *
 * QUÉ PRUEBA
 * ──────────
 * Para un lote de `batchSize` votantes y `voteOptions` opciones:
 *
 *   - cada hoja del lote pertenece al `stateRoot` comprometido (Merkle);
 *   - los totales nuevos son los anteriores más la suma del lote;
 *   - ningún votante excede su `voiceCredits` (evita crear peso de la nada);
 *   - los compromisos publicados corresponden a esos totales con su sal.
 *
 * POR QUÉ HAY SALES
 * ─────────────────
 * Publicar los totales en claro tras cada lote permitiría deducir cómo votó
 * un grupo pequeño comparando dos publicaciones consecutivas. El compromiso
 * es Poseidon(sal, totales), así que solo se revela el resultado final cuando
 * el coordinador decide abrir la sal.
 *
 * ESTADO: escrito y compilado, SIN ceremonia de confianza. El .zkey que
 * produzca `compile.sh` es de una sola parte y sirve para integración, nunca
 * para una elección real.
 */

/// Suma `n` señales. Se aísla para que el acumulador quede explícito.
template Sum(n) {
    signal input in[n];
    signal output out;

    signal partial[n + 1];
    partial[0] <== 0;
    for (var i = 0; i < n; i++) {
        partial[i + 1] <== partial[i] + in[i];
    }
    out <== partial[n];
}

/// Compromiso de un vector de resultados: Poseidon(salt, r[0], ..., r[k-1]).
template ResultsCommitment(voteOptions) {
    signal input salt;
    signal input results[voteOptions];
    signal output out;

    component hasher = Poseidon(voteOptions + 1);
    hasher.inputs[0] <== salt;
    for (var i = 0; i < voteOptions; i++) {
        hasher.inputs[i + 1] <== results[i];
    }
    out <== hasher.out;
}

/**
 * Hoja de estado de un votante: Poseidon(pubKeyX, pubKeyY, voiceCredits, H(votos)).
 *
 * Los votos entran por su hash y no uno a uno para que la aridad de Poseidon
 * no dependa de `voteOptions`: así cambiar el número de opciones no cambia el
 * formato de la hoja.
 */
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

/// Comprueba una ruta Merkle. Misma convención de índices que
/// verify_identity.circom: 0 = el nodo actual va a la izquierda.
template MerkleInclusion(levels) {
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

template MaciTally(stateTreeDepth, batchSize, voteOptions, maxVoiceCredits) {
    // === Privado ===
    signal input pubKeyX[batchSize];
    signal input pubKeyY[batchSize];
    signal input voiceCredits[batchSize];
    signal input votes[batchSize][voteOptions];
    signal input pathElements[batchSize][stateTreeDepth];
    signal input pathIndices[batchSize][stateTreeDepth];

    signal input currentResults[voteOptions];
    signal input currentSalt;
    signal input newResults[voteOptions];
    signal input newSalt;

    // === Público ===
    signal input stateRoot;
    signal input currentResultsCommitment;
    signal input newResultsCommitment;

    // --- 1. Cada hoja del lote pertenece al estado comprometido ---
    // Sin esto, el coordinador podría inventar votantes que nunca se
    // inscribieron y sumarlos al resultado.
    component leaves[batchSize];
    component inclusion[batchSize];

    for (var i = 0; i < batchSize; i++) {
        leaves[i] = StateLeaf(voteOptions);
        leaves[i].pubKeyX <== pubKeyX[i];
        leaves[i].pubKeyY <== pubKeyY[i];
        leaves[i].voiceCredits <== voiceCredits[i];
        for (var j = 0; j < voteOptions; j++) {
            leaves[i].votes[j] <== votes[i][j];
        }

        inclusion[i] = MerkleInclusion(stateTreeDepth);
        inclusion[i].leaf <== leaves[i].out;
        for (var k = 0; k < stateTreeDepth; k++) {
            inclusion[i].pathElements[k] <== pathElements[i][k];
            inclusion[i].pathIndices[k] <== pathIndices[i][k];
        }
        inclusion[i].root === stateRoot;
    }

    // --- 2. Nadie gasta más peso del que tiene ---
    // El límite es lo que impide crear votos de la nada. Se comprueba contra
    // los créditos de la hoja, que ya está atada al estado.
    component spent[batchSize];
    component withinCredits[batchSize];
    component withinMax[batchSize];

    for (var i = 0; i < batchSize; i++) {
        spent[i] = Sum(voteOptions);
        for (var j = 0; j < voteOptions; j++) {
            spent[i].in[j] <== votes[i][j];
        }

        // spent <= voiceCredits
        withinCredits[i] = LessEqThan(64);
        withinCredits[i].in[0] <== spent[i].out;
        withinCredits[i].in[1] <== voiceCredits[i];
        withinCredits[i].out === 1;

        // voiceCredits <= maxVoiceCredits: acota el rango y evita que un
        // valor enorme haga desbordar la suma dentro del campo.
        withinMax[i] = LessEqThan(64);
        withinMax[i].in[0] <== voiceCredits[i];
        withinMax[i].in[1] <== maxVoiceCredits;
        withinMax[i].out === 1;
    }

    // --- 3. Los totales nuevos son los anteriores más el lote ---
    component optionTotals[voteOptions];
    for (var j = 0; j < voteOptions; j++) {
        optionTotals[j] = Sum(batchSize);
        for (var i = 0; i < batchSize; i++) {
            optionTotals[j].in[i] <== votes[i][j];
        }
        newResults[j] === currentResults[j] + optionTotals[j].out;
    }

    // --- 4. Los compromisos publicados corresponden a esos totales ---
    // Ata la prueba a lo que ya se publicó: sin esta comprobación, un lote
    // válido podría aplicarse sobre un resultado previo distinto del anunciado.
    component currentCommitment = ResultsCommitment(voteOptions);
    currentCommitment.salt <== currentSalt;
    for (var j = 0; j < voteOptions; j++) {
        currentCommitment.results[j] <== currentResults[j];
    }
    currentCommitment.out === currentResultsCommitment;

    component newCommitment = ResultsCommitment(voteOptions);
    newCommitment.salt <== newSalt;
    for (var j = 0; j < voteOptions; j++) {
        newCommitment.results[j] <== newResults[j];
    }
    newCommitment.out === newResultsCommitment;
}

// Parámetros del piloto:
//   stateTreeDepth 10 -> 1024 votantes por consulta
//   batchSize      5  -> lotes pequeños, pruebas baratas de generar
//   voteOptions    3  -> a favor / en contra / abstención
//   maxVoiceCredits 1 -> un voto por persona (voto simple, no cuadrático)
//
// El orden de las señales públicas es frontera de protocolo con
// MACICoordinator.publishTally: [stateRoot, currentResultsCommitment,
// newResultsCommitment].
component main {public [stateRoot, currentResultsCommitment, newResultsCommitment]} =
    MaciTally(10, 5, 3, 1);
