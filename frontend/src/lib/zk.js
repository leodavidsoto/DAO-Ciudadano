/**
 * ZK-Client — generación local de pruebas de conocimiento cero (ADR-001, D-2).
 *
 * El paradigma que resuelve el ADR: el navegador prueba localmente que el
 * ciudadano posee un documento válido, y solo publica un `nullifier`. El RUT,
 * la MRZ y cualquier dato del documento NUNCA salen del dispositivo.
 *
 * Este módulo envuelve `snarkjs` (groth16) sobre el circuito
 * `circuits/verify_identity.circom`, cuyas señales son:
 *
 *   entradas privadas : documentIdHash, secret     (jamás se transmiten)
 *   entrada pública   : registryKeyId
 *   salidas públicas  : nullifier, registryKeyIdOut
 *
 *   nullifier = Poseidon(documentIdHash, secret)
 *
 * ─────────────────────────────────────────────────────────────────────────
 * LÍMITES REALES DE ESTA PRUEBA — léelos antes de confiar en ella
 * ─────────────────────────────────────────────────────────────────────────
 * Lo que el circuito prueba HOY: que quien genera la prueba conoce un
 * `documentIdHash` y un `secret`, y que el nullifier deriva de ambos. Eso da
 * unicidad (anti-Sybil) sin revelar el RUT.
 *
 * Lo que NO prueba: que esos datos vengan del Registro Civil. El circuito aún
 * no verifica la firma de EF.SOD, así que un `documentIdHash` inventado
 * produce una prueba aritméticamente válida. Está documentado en
 * `circuits/README.md`, que dice explícitamente que no debe desplegarse así.
 *
 * Además, la ceremonia de confianza de `compile.sh` es de una sola parte:
 * quien la ejecutó conoce el toxic waste y puede fabricar pruebas falsas.
 *
 * Por eso este módulo NUNCA afirma "identidad verificada". Emite una prueba
 * de unicidad y rotula lo que garantiza. La verificación civil real la aporta
 * el claim firmado por el emisor, que es dominio del backend.
 *
 * ─────────────────────────────────────────────────────────────────────────
 * FALLA CERRADO
 * ─────────────────────────────────────────────────────────────────────────
 * Los artefactos (.wasm y .zkey) no viven en el repositorio: se generan con
 * `circuits/compile.sh` y se publican como assets del build. Si no están,
 * `generateIdentityProof` lanza `ZkNotProvisionedError` en vez de devolver
 * algo parecido a una prueba. No hay ruta de degradación silenciosa: una
 * prueba fabricada sería peor que no tener ZK.
 */

// Orden del campo escalar de BN254 (la curva que usa groth16 en snarkjs).
// Toda señal del circuito debe ser un entero menor que este valor.
const BN254_SCALAR_FIELD =
    21888242871839275222246405745257275088548364400416034343698204186575808495617n;

// Los artefactos se sirven como assets estáticos del build, no como fuentes.
// Ver `circuits/README.md`: pesan demasiado para versionarlos.
const WASM_URL = process.env.REACT_APP_ZK_WASM_URL || '/zk/verify_identity.wasm';
const ZKEY_URL = process.env.REACT_APP_ZK_ZKEY_URL || '/zk/verify_identity_final.zkey';
const VKEY_URL = process.env.REACT_APP_ZK_VKEY_URL || '/zk/verification_key.json';

// Clave del registro civil contra la que se genera la prueba. El circuito la
// ata a la prueba para que una generada contra un registro no valga en otro.
// Sin valor configurado no se inventa uno: se exige explícitamente.
const REGISTRY_KEY_ID = process.env.REACT_APP_ZK_REGISTRY_KEY_ID || '';

const SECRET_STORAGE_KEY = 'zk_identity_secret_v1';

/** Los artefactos del circuito no están publicados en este despliegue. */
export class ZkNotProvisionedError extends Error {
    constructor(message, missing = []) {
        super(message);
        this.name = 'ZkNotProvisionedError';
        this.missing = missing;
    }
}

/** La generación o verificación de la prueba falló. */
export class ZkProofError extends Error {
    constructor(message) {
        super(message);
        this.name = 'ZkProofError';
    }
}

// === Utilidades de campo ===

/**
 * Reduce bytes arbitrarios a un elemento del campo escalar de BN254.
 *
 * Sin la reducción modular, un digest de 256 bits puede superar el orden del
 * campo y snarkjs lo rechazaría (o peor, lo truncaría de forma no evidente).
 */
export function bytesToFieldElement(bytes) {
    let value = 0n;
    for (const byte of bytes) {
        value = (value << 8n) | BigInt(byte);
    }
    const reduced = value % BN254_SCALAR_FIELD;
    // El circuito rechaza el cero (colisionaría nullifiers trivialmente).
    return reduced === 0n ? 1n : reduced;
}

/** SHA-256 sobre una cadena, reducido a elemento de campo. */
export async function hashToField(text) {
    if (typeof text !== 'string' || !text) {
        throw new ZkProofError('No se puede derivar un elemento de campo de un valor vacío.');
    }
    if (!globalThis.crypto?.subtle) {
        throw new ZkProofError(
            'Web Crypto no está disponible. La generación de pruebas exige un contexto seguro (HTTPS o localhost).'
        );
    }
    const digest = await globalThis.crypto.subtle.digest(
        'SHA-256',
        new TextEncoder().encode(text)
    );
    return bytesToFieldElement(new Uint8Array(digest));
}

// === Secreto del ciudadano ===

/**
 * Devuelve el secreto local, creándolo la primera vez.
 *
 * Es lo que impide que un tercero que conozca el RUT recalcule el nullifier y
 * rastree a la persona. Consecuencia importante: si se pierde, el ciudadano
 * genera un nullifier distinto para el mismo documento. Por eso hay
 * `exportSecret`/`importSecret`: la recuperación es un requisito del producto,
 * no un extra.
 */
export function getOrCreateSecret() {
    const stored = globalThis.localStorage?.getItem(SECRET_STORAGE_KEY);
    if (stored) return stored;

    if (!globalThis.crypto?.getRandomValues) {
        throw new ZkProofError(
            'No hay generador criptográfico disponible; no se puede crear un secreto seguro.'
        );
    }
    const random = new Uint8Array(31); // 248 bits: siempre cabe en el campo
    globalThis.crypto.getRandomValues(random);
    const secret = bytesToFieldElement(random).toString();
    globalThis.localStorage?.setItem(SECRET_STORAGE_KEY, secret);
    return secret;
}

export function hasSecret() {
    return Boolean(globalThis.localStorage?.getItem(SECRET_STORAGE_KEY));
}

/** Exporta el secreto para que el ciudadano pueda respaldarlo. */
export function exportSecret() {
    return globalThis.localStorage?.getItem(SECRET_STORAGE_KEY) || null;
}

/** Restaura un secreto respaldado (misma cédula -> mismo nullifier). */
export function importSecret(secret) {
    const trimmed = String(secret || '').trim();
    if (!/^\d+$/.test(trimmed)) {
        throw new ZkProofError('El secreto debe ser un entero decimal.');
    }
    const value = BigInt(trimmed);
    if (value <= 0n || value >= BN254_SCALAR_FIELD) {
        throw new ZkProofError('El secreto está fuera del campo escalar admitido.');
    }
    globalThis.localStorage?.setItem(SECRET_STORAGE_KEY, trimmed);
    return trimmed;
}

/** Olvida el secreto de este dispositivo. Sin respaldo, es irreversible. */
export function forgetSecret() {
    globalThis.localStorage?.removeItem(SECRET_STORAGE_KEY);
}

// === Disponibilidad de los artefactos ===

async function artifactExists(url) {
    try {
        // HEAD evita descargar el .zkey (decenas de MB) solo para comprobar.
        const response = await fetch(url, { method: 'HEAD' });
        if (!response.ok) return false;
        // Un SPA suele responder index.html a rutas desconocidas: un HTML aquí
        // significa que el asset no existe, aunque el status sea 200.
        const type = response.headers.get('content-type') || '';
        return !type.includes('text/html');
    } catch {
        return false;
    }
}

/**
 * Comprueba si este despliegue puede generar pruebas.
 * Devuelve `{ ready, missing }` — nunca lanza, para que la interfaz pueda
 * mostrar el estado sin envolverlo en try/catch.
 */
export async function checkZkAvailability() {
    const missing = [];
    if (!REGISTRY_KEY_ID) missing.push('REACT_APP_ZK_REGISTRY_KEY_ID');

    const [wasmOk, zkeyOk] = await Promise.all([
        artifactExists(WASM_URL),
        artifactExists(ZKEY_URL),
    ]);
    if (!wasmOk) missing.push(WASM_URL);
    if (!zkeyOk) missing.push(ZKEY_URL);

    return { ready: missing.length === 0, missing };
}

/** ¿Está activada la ruta de minteo con prueba ZK en este despliegue? */
export function isZkMintEnabled() {
    return String(process.env.REACT_APP_ZK_MINT || '').toLowerCase() === 'true';
}

// === Generación de la prueba ===

/**
 * snarkjs pesa varios MB. Se importa bajo demanda para no cargarlo en el
 * bundle inicial de quien solo entra a leer propuestas.
 */
async function loadSnarkjs() {
    try {
        return await import('snarkjs');
    } catch (error) {
        throw new ZkProofError('No se pudo cargar la biblioteca de pruebas (snarkjs).');
    }
}

/**
 * Genera la prueba ZK localmente.
 *
 * @param {object} params
 * @param {string} params.documentId  Identificador del documento leído del chip
 *                                    (contenido de DG1). No se transmite: solo
 *                                    se usa para derivar `documentIdHash`.
 * @returns {Promise<object>} prueba, señales públicas, nullifier y calldata
 *                            lista para el verificador Solidity.
 */
export async function generateIdentityProof({ documentId }) {
    if (!documentId) {
        throw new ZkProofError(
            'Falta el identificador del documento. Sin una lectura real del chip no hay nada que probar.'
        );
    }

    const availability = await checkZkAvailability();
    if (!availability.ready) {
        throw new ZkNotProvisionedError(
            'Este despliegue no tiene publicados los artefactos del circuito, así que no puede generar una prueba. ' +
            'Genera el circuito con circuits/compile.sh y publica el .wasm y el .zkey como assets del build.',
            availability.missing
        );
    }

    const snarkjs = await loadSnarkjs();

    const documentIdHash = await hashToField(documentId);
    const secret = getOrCreateSecret();
    const registryKeyId = await hashToField(REGISTRY_KEY_ID);

    const input = {
        documentIdHash: documentIdHash.toString(),
        secret,
        registryKeyId: registryKeyId.toString(),
    };

    let proof;
    let publicSignals;
    try {
        ({ proof, publicSignals } = await snarkjs.groth16.fullProve(
            input,
            WASM_URL,
            ZKEY_URL
        ));
    } catch (error) {
        // El mensaje del prover puede incluir rutas y detalles del circuito;
        // no se refleja tal cual al ciudadano.
        console.error('ZK proof generation failed:', error);
        throw new ZkProofError(
            'No se pudo generar la prueba en este dispositivo. Revisa que los artefactos del circuito correspondan al circuito compilado.'
        );
    }

    // Convención de circom: primero las señales de salida, después las
    // entradas declaradas públicas. Para verify_identity.circom eso es
    // [nullifier, registryKeyIdOut, registryKeyId].
    const [nullifier, registryKeyIdOut] = publicSignals;

    if (registryKeyIdOut !== registryKeyId.toString()) {
        throw new ZkProofError(
            'La prueba no quedó atada a la clave de registro esperada; se descarta.'
        );
    }

    return {
        proof,
        publicSignals,
        nullifier,
        registryKeyId: registryKeyId.toString(),
        solidity: await toSolidityCalldata(snarkjs, proof, publicSignals),
    };
}

/**
 * Formatea la prueba como la espera un verificador Groth16 de Solidity
 * (`uint[2] a, uint[2][2] b, uint[2] c, uint[] input`).
 *
 * Se delega en `exportSolidityCallData` de snarkjs en vez de reordenar los
 * componentes a mano: el punto G2 exige un intercambio de coordenadas que es
 * fácil de invertir y produce una prueba que falla sin explicación.
 */
async function toSolidityCalldata(snarkjs, proof, publicSignals) {
    const raw = await snarkjs.groth16.exportSolidityCallData(proof, publicSignals);
    // Devuelve algo como: ["0x..","0x.."],[["0x..",..],..],["0x..",".."],["0x.."]
    const flat = JSON.parse(`[${raw}]`);
    return { a: flat[0], b: flat[1], c: flat[2], input: flat[3] };
}

/**
 * Verifica la prueba en el propio navegador antes de enviarla.
 *
 * No sustituye la verificación on-chain — el cliente no es una autoridad—,
 * pero evita gastar una transacción patrocinada en una prueba inválida.
 * Si la clave de verificación no está publicada, devuelve `null` (desconocido)
 * en lugar de `true`: no saber no es lo mismo que estar bien.
 */
export async function verifyProofLocally(proof, publicSignals) {
    let vkey;
    try {
        const response = await fetch(VKEY_URL);
        if (!response.ok) return null;
        vkey = await response.json();
    } catch {
        return null;
    }

    try {
        const snarkjs = await loadSnarkjs();
        return await snarkjs.groth16.verify(vkey, publicSignals, proof);
    } catch (error) {
        console.error('Local proof verification failed:', error);
        return false;
    }
}
