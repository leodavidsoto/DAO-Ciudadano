pragma circom 2.1.6;

include "circomlib/circuits/poseidon.circom";
include "circomlib/circuits/comparators.circom";
include "circomlib/circuits/bitify.circom";

/*
 * verify_identity.circom — base del flujo ZKP de identidad soberana.
 *
 * ESTADO: PARCIAL Y NO USABLE EN PRODUCCIÓN TODAVÍA. Lee la sección
 * "Qué falta" del README de este directorio antes de tocarlo.
 *
 * Qué prueba HOY (implementado y funcional):
 *   - Que quien genera la prueba conoce un identificador de documento y un
 *     secreto, y que el `nullifier` publicado se deriva determinísticamente
 *     de ambos. Eso da unicidad: la misma cédula produce siempre el mismo
 *     nullifier, así que el contrato puede rechazar el segundo registro
 *     (anti-Sybil), sin que el nullifier revele el RUT.
 *
 * Qué NO prueba todavía (el trabajo pesado, ver README):
 *   - Que los datos del documento estén realmente firmados por el Registro
 *     Civil. Eso exige verificar dentro del circuito la firma RSA/ECDSA de
 *     EF.SOD y el encadenamiento de hashes DG1 -> SOD. Sin eso, alguien
 *     puede inventar un documentId y obtener una prueba "válida".
 *
 * Por eso el circuito NO debe desplegarse como está: probaría unicidad de
 * algo no autenticado. Se marca explícito en vez de aparentar completitud.
 */

template VerifyIdentity() {
    // === Entradas privadas (NUNCA salen del dispositivo) ===
    // Hash del contenido de DG1 (los datos de la MRZ leídos del chip).
    // Se pasa ya hasheado para no meter 88+ bytes de MRZ como señales.
    signal input documentIdHash;
    // Secreto del usuario: impide que un tercero que conozca el RUT pueda
    // recalcular el nullifier y rastrear a la persona.
    signal input secret;

    // === Entrada pública ===
    // Identificador de la clave del registro civil contra la que se valida.
    // Hoy solo se ata a la prueba (para que una prueba de un registro no
    // sirva en otro); cuando se implemente la verificación de firma, este
    // será el módulo/clave real contra el que se verifica EF.SOD.
    signal input registryKeyId;

    // === Salidas públicas ===
    signal output nullifier;
    signal output registryKeyIdOut;

    // Nullifier = Poseidon(documentIdHash, secret)
    // Poseidon y no SHA-256 porque es ~100x más barato en restricciones
    // dentro de un circuito aritmético.
    component hasher = Poseidon(2);
    hasher.inputs[0] <== documentIdHash;
    hasher.inputs[1] <== secret;
    nullifier <== hasher.out;

    // Ata la clave del registro a la prueba: sin esto, el verificador no
    // podría distinguir contra qué registro se generó.
    registryKeyIdOut <== registryKeyId;

    // Restricciones de sanidad: ninguna entrada puede ser 0. Un
    // documentIdHash o secret en cero produciría nullifiers colisionables
    // triviales.
    component docNonZero = IsZero();
    docNonZero.in <== documentIdHash;
    docNonZero.out === 0;

    component secretNonZero = IsZero();
    secretNonZero.in <== secret;
    secretNonZero.out === 0;
}

// registryKeyId es público: el contrato debe poder comprobar que la prueba
// se generó contra la clave del registro que él considera válida.
component main {public [registryKeyId]} = VerifyIdentity();
