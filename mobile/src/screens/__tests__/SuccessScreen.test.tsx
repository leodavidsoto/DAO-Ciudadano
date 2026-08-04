jest.mock('react-native-quick-crypto', () => require('crypto'));

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { TouchableOpacity } from 'react-native';
import SuccessScreen from '../SuccessScreen';
import {
    parseNativePassportReadResult,
    type VerifiedNFCReadResult,
} from '../../services/nfcService';

function verifiedResult(): VerifiedNFCReadResult {
    const result = parseNativePassportReadResult({
        identityVerified: true,
        data: {
            documentNumber: 'A1234567',
            firstName: 'ANA',
            lastName: 'PEREZ',
            dateOfBirth: '900101',
            dateOfExpiry: '300101',
            nationality: 'CHL',
            issuingState: 'CHL',
            sex: 'F',
            serialNumber: '04DEADBEEF',
            rut: '11.111.111-1',
        },
        verification: {
            passed: true,
            dataGroupHashesMatch: true,
            sodSignatureValid: true,
            certificateChainTrusted: true,
            paceEstablished: true,
            requiredDataGroupsPresent: true,
            issuingStateIsChile: true,
            documentProfileIsIdentityCard: true,
            documentNotExpired: true,
            countrySigningCertificateIsChile: true,
            trustAnchorsInstalled: 2,
            documentSigner: 'CN=Document Signer',
            documentSignerIssuer: 'CN=CSCA Chile',
            countrySigningCertificateSubject:
                'C=CL,O=Servicio de Registro Civil e Identificacion,CN=CSCA Chile',
            failures: [],
        },
    });
    if (result.status !== 'verified') throw new Error('Invalid verified fixture');
    return result;
}

function renderedText(renderer: ReactTestRenderer.ReactTestRenderer): string {
    const collect = (node: unknown): string => {
        if (typeof node === 'string' || typeof node === 'number') return String(node);
        if (Array.isArray(node)) return node.map(collect).join(' ');
        if (typeof node !== 'object' || node === null || !('children' in node)) return '';
        return collect((node as { children?: unknown }).children);
    };
    return collect(renderer.toJSON());
}

describe('SuccessScreen verification gate', () => {
    it('never continues an absent or unverified route payload to Wallet', async () => {
        const navigation = { navigate: jest.fn() };
        let renderer!: ReactTestRenderer.ReactTestRenderer;

        await ReactTestRenderer.act(() => {
            renderer = ReactTestRenderer.create(
                <SuccessScreen navigation={navigation} route={{ params: {} }} />,
            );
        });

        await ReactTestRenderer.act(() => {
            renderer.root.findByType(TouchableOpacity).props.onPress();
        });

        expect(navigation.navigate).toHaveBeenCalledWith('Scan');
        expect(navigation.navigate).not.toHaveBeenCalledWith('Wallet');
        expect(renderedText(renderer)).toContain('LECTURA NO VERIFICADA');
    });

    it('shows authenticated evidence without serial, UID, documentHash or ZK claims', async () => {
        const navigation = { navigate: jest.fn() };
        let renderer!: ReactTestRenderer.ReactTestRenderer;

        await ReactTestRenderer.act(() => {
            renderer = ReactTestRenderer.create(
                <SuccessScreen
                    navigation={navigation}
                    route={{ params: { result: verifiedResult() } }}
                />,
            );
        });

        const text = renderedText(renderer);
        expect(text).toContain('EVIDENCIA VERIFICADA');
        expect(text).toContain('Firma EF.SOD');
        expect(text).not.toMatch(/serial|UID|documentHash|Zero-Knowledge|\bZK\b/i);

        await ReactTestRenderer.act(() => {
            renderer.root.findByType(TouchableOpacity).props.onPress();
        });
        expect(navigation.navigate).toHaveBeenCalledWith('Wallet');
    });
});
