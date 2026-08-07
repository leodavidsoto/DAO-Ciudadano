/**
 * BAC (Basic Access Control) — capa criptográfica, ICAO 9303 Parte 11.
 *
 * Primitivas puras y determinísticas: no tocan NFC ni estado. Todo lo que
 * hay acá está verificado contra los vectores publicados en el ejemplo
 * trabajado de ICAO 9303 (ver __tests__/bacCrypto.test.ts) — si alguien
 * cambia algo y rompe un vector, el test lo detecta.
 *
 * Por qué importa: el circuito ZKP (ver /circuits) necesita probar que la
 * firma del Registro Civil sobre los datos del documento es válida. Esa
 * firma vive en EF.SOD, y EF.SOD solo se puede leer después de establecer
 * el canal seguro BAC. Sin esto, no hay nada que probar.
 *
 * NOTA SOBRE DES SIMPLE: el Retail MAC (ISO 9797-1 Algoritmo 3) necesita
 * DES de una sola llave, pero muchos backends modernos (BoringSSL, Node 22
 * sin legacy provider) ya no exponen 'des-cbc'. Se emula con 3DES usando la
 * misma llave tres veces: E_K(D_K(E_K(x))) == E_K(x). Verificado contra los
 * vectores, no es un atajo especulativo.
 */
import { Buffer } from 'buffer';

// El módulo nativo se resuelve una sola vez y falla CERRADO: si no hay
// 3DES disponible no se degrada a "leer sin autenticar" (eso daría datos
// que el chip no autenticó, indistinguibles de datos inventados).
let _crypto: any = null;
function getCrypto(): any {
    if (_crypto) return _crypto;
    try {
        _crypto = require('react-native-quick-crypto');
    } catch (e: any) {
        throw new Error(
            'No se pudo cargar react-native-quick-crypto; sin 3DES no se puede ' +
            'establecer el canal seguro con la cédula. Detalle: ' + (e?.message || e),
        );
    }
    return _crypto;
}


function tripleKey(key16: Buffer): Buffer {
    // 3DES de 2 llaves (K1|K2) expresado como K1|K2|K1, que es lo que
    // esperan las APIs de 'des-ede3-cbc'.
    return Buffer.concat([key16, key16.subarray(0, 8)]);
}

export function xor(a: Buffer, b: Buffer): Buffer {
    const out = Buffer.alloc(a.length);
    for (let i = 0; i < a.length; i++) out[i] = a[i] ^ b[i];
    return out;
}

/** DES simple en CBC, emulado con 3DES de llave repetida (ver nota arriba). */
function desEncryptCBC(key8: Buffer, iv: Buffer, data: Buffer): Buffer {
    const c = getCrypto().createCipheriv('des-ede3-cbc', Buffer.concat([key8, key8, key8]), iv);
    c.setAutoPadding(false);
    return Buffer.concat([c.update(data), c.final()]);
}

function desDecryptCBC(key8: Buffer, iv: Buffer, data: Buffer): Buffer {
    const d = getCrypto().createDecipheriv('des-ede3-cbc', Buffer.concat([key8, key8, key8]), iv);
    d.setAutoPadding(false);
    return Buffer.concat([d.update(data), d.final()]);
}

export function des3EncryptCBC(key16: Buffer, iv: Buffer, data: Buffer): Buffer {
    const c = getCrypto().createCipheriv('des-ede3-cbc', tripleKey(key16), iv);
    c.setAutoPadding(false);
    return Buffer.concat([c.update(data), c.final()]);
}

export function des3DecryptCBC(key16: Buffer, iv: Buffer, data: Buffer): Buffer {
    const d = getCrypto().createDecipheriv('des-ede3-cbc', tripleKey(key16), iv);
    d.setAutoPadding(false);
    return Buffer.concat([d.update(data), d.final()]);
}

function sha1(data: Buffer): Buffer {
    return Buffer.from(getCrypto().createHash('sha1').update(data).digest());
}

/** ICAO exige llaves DES con paridad impar por byte. */
export function adjustParity(buf: Buffer): Buffer {
    const out = Buffer.alloc(buf.length);
    buf.copy(out);
    for (let i = 0; i < out.length; i++) {
        let ones = 0;
        for (let bit = 1; bit < 8; bit++) if ((out[i] >> bit) & 1) ones++;
        out[i] = ones % 2 === 0 ? out[i] | 1 : out[i] & 0xfe;
    }
    return out;
}

/** Dígito verificador MRZ (ICAO 9303, pesos 7-3-1). */
export function mrzCheckDigit(str: string): number {
    const weights = [7, 3, 1];
    let sum = 0;
    for (let i = 0; i < str.length; i++) {
        const ch = str[i].toUpperCase();
        let v = 0;
        if (ch >= '0' && ch <= '9') v = ch.charCodeAt(0) - 48;
        else if (ch >= 'A' && ch <= 'Z') v = ch.charCodeAt(0) - 55;
        else v = 0; // '<' y cualquier relleno
        sum += v * weights[i % 3];
    }
    return sum % 10;
}

export interface MRZKeyData {
    documentNumber: string;
    dateOfBirth: string;   // YYMMDD
    dateOfExpiry: string;  // YYMMDD
}

/**
 * MRZ_information: número de documento **rellenado a 9 caracteres con '<'**
 * tal como aparece en la MRZ, seguido de su dígito verificador, y lo mismo
 * para fecha de nacimiento y de expiración.
 *
 * El relleno a 9 no es cosmético: sin él el Kseed sale distinto y la
 * autenticación con el chip falla. (La versión anterior de nfcService.ts
 * omitía el relleno — no se notaba porque nunca llegaba a hablar con el chip.)
 */
export function buildMRZInformation(mrz: MRZKeyData): string {
    const doc = (mrz.documentNumber || '').toUpperCase().padEnd(9, '<');
    return (
        doc + mrzCheckDigit(doc) +
        mrz.dateOfBirth + mrzCheckDigit(mrz.dateOfBirth) +
        mrz.dateOfExpiry + mrzCheckDigit(mrz.dateOfExpiry)
    );
}

/** Kseed = SHA-1(MRZ_information)[0..16] */
export function computeKSeed(mrz: MRZKeyData): Buffer {
    return sha1(Buffer.from(buildMRZInformation(mrz), 'ascii')).subarray(0, 16);
}

/** Derivación de llave ICAO: counter 1 = cifrado, 2 = MAC. */
export function deriveKey(kseed: Buffer, counter: 1 | 2): Buffer {
    const digest = sha1(Buffer.concat([kseed, Buffer.from([0, 0, 0, counter])]));
    return Buffer.concat([
        adjustParity(digest.subarray(0, 8)),
        adjustParity(digest.subarray(8, 16)),
    ]);
}

export interface BACKeys {
    kenc: Buffer;
    kmac: Buffer;
}

export function deriveBACKeys(mrz: MRZKeyData): BACKeys {
    const kseed = computeKSeed(mrz);
    return { kenc: deriveKey(kseed, 1), kmac: deriveKey(kseed, 2) };
}

/** Relleno ISO 9797-1 método 2: 0x80 y luego ceros hasta múltiplo de 8. */
export function pad(data: Buffer): Buffer {
    const padLen = 8 - (data.length % 8);
    return Buffer.concat([data, Buffer.from([0x80]), Buffer.alloc(padLen - 1)]);
}

export function unpad(data: Buffer): Buffer {
    let i = data.length - 1;
    while (i >= 0 && data[i] === 0x00) i--;
    if (i < 0 || data[i] !== 0x80) {
        throw new Error('Relleno ISO 9797-1 inválido en la respuesta del chip');
    }
    return data.subarray(0, i);
}

export function retailMac(kmac: Buffer, data: Buffer): Buffer {
    const ka = kmac.subarray(0, 8);
    const kb = kmac.subarray(8, 16);
    const padded = pad(data);

    // Paso 1: Cifrar todos los bloques con DES-CBC y un IV en cero usando la llave Ka.
    // Esto es algorítmicamente equivalente al bucle manual, pero se hace todo
    // en la capa nativa (OpenSSL), ahorrando miles de asignaciones de memoria JNI
    // y evitando la mutación in-place del IV estático.
    const c = getCrypto().createCipheriv('des-ede3-cbc', Buffer.concat([ka, ka, ka]), Buffer.alloc(8));
    c.setAutoPadding(false);
    const cipherText = Buffer.concat([c.update(padded), c.final()]);
    
    // Paso 2: Tomar el último bloque resultante.
    // Anotado como `Buffer` a secas: `subarray` conserva el `ArrayBuffer`
    // concreto del origen, mientras que las funciones DES devuelven
    // `Buffer<ArrayBufferLike>`. Sin la anotación, el reasignado de abajo no
    // compila.
    let y: Buffer = cipherText.subarray(cipherText.length - 8);

    // Paso 3: Descifrar el último bloque con Kb y cifrar con Ka.
    // Al ser un solo bloque, el cifrado CBC con IV cero es equivalente a ECB.
    y = desDecryptCBC(kb, Buffer.alloc(8), Buffer.from(y));
    y = desEncryptCBC(ka, Buffer.alloc(8), Buffer.from(y));

    return y;
}

/** Llaves de sesión tras la autenticación mutua: Kseed = K.IFD XOR K.ICC */
export function deriveSessionKeys(kIFD: Buffer, kICC: Buffer): BACKeys {
    const kseed = xor(kIFD, kICC);
    return { kenc: deriveKey(kseed, 1), kmac: deriveKey(kseed, 2) };
}

/** SSC inicial = últimos 4 bytes de RND.ICC || últimos 4 de RND.IFD */
export function initialSSC(rndICC: Buffer, rndIFD: Buffer): Buffer {
    return Buffer.concat([rndICC.subarray(4, 8), rndIFD.subarray(4, 8)]);
}

/** Incrementa el SSC como entero big-endian de 8 bytes. */
export function incrementSSC(ssc: Buffer): Buffer {
    const out = Buffer.alloc(ssc.length);
    ssc.copy(out);
    for (let i = out.length - 1; i >= 0; i--) {
        out[i] = (out[i] + 1) & 0xff;
        if (out[i] !== 0) break;
    }
    return out;
}
