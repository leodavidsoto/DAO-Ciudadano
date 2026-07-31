/**
 * Vectores de prueba oficiales de ICAO 9303 Parte 11 (ejemplo trabajado).
 *
 * Estos valores NO son inventados ni generados por nuestra propia
 * implementación: vienen del estándar. Si alguien "optimiza" bacCrypto.ts y
 * rompe la interoperabilidad con chips reales, estos tests fallan acá en vez
 * de fallar silenciosamente contra una cédula física.
 *
 * react-native-quick-crypto se sustituye por el `crypto` de Node: la API que
 * usamos (createHash/createCipheriv/createDecipheriv) es la misma, así que el
 * test ejercita el algoritmo real, no un doble.
 */
jest.mock('react-native-quick-crypto', () => require('crypto'));

import { Buffer } from 'buffer';
import {
    buildMRZInformation,
    computeKSeed,
    deriveKey,
    deriveBACKeys,
    retailMac,
    des3EncryptCBC,
    des3DecryptCBC,
    deriveSessionKeys,
    initialSSC,
    incrementSSC,
    mrzCheckDigit,
    pad,
    unpad,
    xor,
} from '../bacCrypto';

const hex = (s: string) => Buffer.from(s.replace(/\s/g, ''), 'hex');
const upper = (b: Buffer) => b.toString('hex').toUpperCase();

// Documento del ejemplo trabajado de ICAO 9303
const MRZ = {
    documentNumber: 'L898902C',
    dateOfBirth: '690806',
    dateOfExpiry: '940623',
};

describe('MRZ y dígitos verificadores', () => {
    it('calcula los dígitos verificadores del ejemplo ICAO', () => {
        expect(mrzCheckDigit('L898902C<')).toBe(3);
        expect(mrzCheckDigit('690806')).toBe(1);
        expect(mrzCheckDigit('940623')).toBe(6);
    });

    it('rellena el número de documento a 9 caracteres con <', () => {
        // Sin este relleno el Kseed sale distinto y el chip rechaza la
        // autenticación. Es exactamente el bug que tenía la versión previa.
        expect(buildMRZInformation(MRZ)).toBe('L898902C<369080619406236');
    });
});

describe('Derivación de llaves BAC (ICAO 9303 Parte 11)', () => {
    it('deriva el Kseed del estándar', () => {
        expect(upper(computeKSeed(MRZ))).toBe('239AB9CB282DAF66231DC5A4DF6BFBAE');
    });

    it('deriva Kenc y Kmac del estándar', () => {
        const { kenc, kmac } = deriveBACKeys(MRZ);
        expect(upper(kenc)).toBe('AB94FDECF2674FDFB9B391F85D7F76F2');
        expect(upper(kmac)).toBe('7962D9ECE03D1ACD4C76089DCE131543');
    });

    it('aplica paridad impar a cada byte de las llaves', () => {
        const { kenc, kmac } = deriveBACKeys(MRZ);
        for (const key of [kenc, kmac]) {
            for (const byte of key) {
                const ones = byte.toString(2).split('1').length - 1;
                expect(ones % 2).toBe(1);
            }
        }
    });
});

describe('Autenticación mutua (ejemplo trabajado ICAO)', () => {
    const RND_IFD = hex('781723860C06C226');
    const RND_ICC = hex('4608F91988702212');
    const K_IFD = hex('0B795240CB7049B01C19B33E32804F0B');

    it('cifra el comando de autenticación igual que el estándar', () => {
        const { kenc } = deriveBACKeys(MRZ);
        const S = Buffer.concat([RND_IFD, RND_ICC, K_IFD]);
        const eIFD = des3EncryptCBC(kenc, Buffer.alloc(8), S);
        expect(upper(eIFD)).toBe(
            '72C29C2371CC9BDB65B779B8E8D37B29ECC154AA56A8799FAE2F498F76ED92F2',
        );
    });

    it('calcula el Retail MAC igual que el estándar', () => {
        const { kenc, kmac } = deriveBACKeys(MRZ);
        const S = Buffer.concat([RND_IFD, RND_ICC, K_IFD]);
        const eIFD = des3EncryptCBC(kenc, Buffer.alloc(8), S);
        expect(upper(retailMac(kmac, eIFD))).toBe('5F1448EEA8AD90A7');
    });

    it('el descifrado revierte el cifrado', () => {
        const { kenc } = deriveBACKeys(MRZ);
        const S = Buffer.concat([RND_IFD, RND_ICC, K_IFD]);
        const eIFD = des3EncryptCBC(kenc, Buffer.alloc(8), S);
        expect(upper(des3DecryptCBC(kenc, Buffer.alloc(8), eIFD))).toBe(upper(S));
    });
});

describe('Llaves de sesión y SSC', () => {
    it('deriva las llaves de sesión desde K.IFD XOR K.ICC', () => {
        const kIFD = hex('0B795240CB7049B01C19B33E32804F0B');
        const kICC = hex('0B4F80323EB3191CB04970CB4052790E');
        const session = deriveSessionKeys(kIFD, kICC);
        // El Kseed de sesión es el XOR; verificamos que la derivación sea la
        // misma función ICAO (counter 1/2) aplicada a ese XOR.
        const expected = deriveKey(xor(kIFD, kICC), 1);
        expect(upper(session.kenc)).toBe(upper(expected));
    });

    it('arma el SSC inicial con los últimos 4 bytes de cada aleatorio', () => {
        const ssc = initialSSC(hex('4608F91988702212'), hex('781723860C06C226'));
        expect(upper(ssc)).toBe('887022120C06C226');
    });

    it('incrementa el SSC con acarreo', () => {
        expect(upper(incrementSSC(hex('0000000000000001')))).toBe('0000000000000002');
        expect(upper(incrementSSC(hex('00000000000000FF')))).toBe('0000000000000100');
        expect(upper(incrementSSC(hex('FFFFFFFFFFFFFFFF')))).toBe('0000000000000000');
    });
});

describe('Relleno ISO 9797-1 método 2', () => {
    it('rellena y revierte', () => {
        const data = Buffer.from([1, 2, 3]);
        expect(upper(pad(data))).toBe('0102038000000000');
        expect(upper(unpad(pad(data)))).toBe('010203');
    });

    it('agrega un bloque completo cuando ya es múltiplo de 8', () => {
        const data = Buffer.alloc(8, 0xaa);
        expect(pad(data).length).toBe(16);
        expect(upper(unpad(pad(data)))).toBe(upper(data));
    });

    it('rechaza un relleno inválido en vez de devolver basura', () => {
        expect(() => unpad(Buffer.from([1, 2, 3, 4]))).toThrow(/Relleno/);
    });
});
