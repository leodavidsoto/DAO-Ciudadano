jest.mock('react-native-quick-crypto', () => require('crypto'));

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { TouchableOpacity } from 'react-native';
import SuccessScreen, { AUTO_ADVANCE_DELAY_MS } from '../SuccessScreen';
import {
    OnboardingProvider,
    useOnboarding,
    type IdentityGrants,
} from '../../context/OnboardingContext';
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
        files: { sod: 'RUYuU09E', dg1: 'REcx', dg2: 'REcy' },
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

/** A grant that dies `ms` from now. Negative means it is already worthless. */
function grantsExpiringIn(ms: number): IdentityGrants {
    return {
        identityGrant: 'identity.grant.fixture',
        membershipGrant: 'membership.grant.fixture',
        assuranceLevel: 'CEDULA_NFC_PASSIVE',
        membershipGrantExpiresAt: Date.now() + ms,
    };
}

/**
 * Fills the context before the screen mounts, like ScanScreen does: it stores
 * the grants and only then navigates. Mounting Success first would make
 * `readyToMint` briefly false and hide the ordering the real flow guarantees.
 */
const SeedGrants: React.FC<{
    grants: IdentityGrants | null;
    children: React.ReactNode;
}> = ({ grants, children }) => {
    const { grants: stored, setVerifiedIdentity } = useOnboarding();
    React.useEffect(() => {
        if (grants) setVerifiedIdentity(grants, verifiedResult().data);
    }, [grants, setVerifiedIdentity]);
    if (grants && !stored) return null;
    return <>{children}</>;
};

async function renderSuccess(
    params: { result?: VerifiedNFCReadResult; grantIssued?: boolean },
    grants: IdentityGrants | null = null,
) {
    const navigation = { navigate: jest.fn() };
    let renderer!: ReactTestRenderer.ReactTestRenderer;

    await ReactTestRenderer.act(() => {
        renderer = ReactTestRenderer.create(
            <OnboardingProvider>
                <SeedGrants grants={grants}>
                    <SuccessScreen navigation={navigation} route={{ params }} />
                </SeedGrants>
            </OnboardingProvider>,
        );
    });

    return { renderer, navigation };
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
        const { renderer, navigation } = await renderSuccess({});

        await ReactTestRenderer.act(() => {
            renderer.root.findByType(TouchableOpacity).props.onPress();
        });

        expect(navigation.navigate).toHaveBeenCalledWith('Scan');
        expect(navigation.navigate).not.toHaveBeenCalledWith('Wallet');
        expect(renderedText(renderer)).toContain('LECTURA NO VERIFICADA');
    });

    it('shows authenticated evidence without serial, UID, documentHash or ZK claims', async () => {
        const { renderer, navigation } = await renderSuccess({ result: verifiedResult() });

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

describe('SuccessScreen auto-advance to minting', () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it('advances by itself once the server issued a live grant', async () => {
        const { renderer, navigation } = await renderSuccess(
            { result: verifiedResult(), grantIssued: true },
            grantsExpiringIn(15 * 60 * 1000),
        );

        expect(renderedText(renderer)).toContain('Continuando al minteo');
        expect(navigation.navigate).not.toHaveBeenCalled();

        await ReactTestRenderer.act(() => {
            jest.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS);
        });
        expect(navigation.navigate).toHaveBeenCalledWith('Wallet');
    });

    it('advances exactly once, even if the citizen also taps continue', async () => {
        const { renderer, navigation } = await renderSuccess(
            { result: verifiedResult(), grantIssued: true },
            grantsExpiringIn(15 * 60 * 1000),
        );

        await ReactTestRenderer.act(() => {
            renderer.root.findByType(TouchableOpacity).props.onPress();
            jest.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS);
        });

        expect(navigation.navigate).toHaveBeenCalledTimes(1);
        expect(navigation.navigate).toHaveBeenCalledWith('Wallet');
    });

    it('stays put on a local-only verification: no grant, no enrolment', async () => {
        const { renderer, navigation } = await renderSuccess({ result: verifiedResult() });

        await ReactTestRenderer.act(() => {
            jest.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS * 3);
        });

        expect(navigation.navigate).not.toHaveBeenCalled();
        expect(renderedText(renderer)).not.toContain('Continuando al minteo');
    });

    it('does not trust the route flag when no grant reached the context', async () => {
        // A `grantIssued: true` that nobody backed with a stored grant would
        // open the mint screen on nothing.
        const { navigation } = await renderSuccess({
            result: verifiedResult(),
            grantIssued: true,
        });

        await ReactTestRenderer.act(() => {
            jest.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS * 3);
        });
        expect(navigation.navigate).not.toHaveBeenCalled();
    });

    it('does not advance on a grant that already expired', async () => {
        const { renderer, navigation } = await renderSuccess(
            { result: verifiedResult(), grantIssued: true },
            grantsExpiringIn(-1000),
        );

        await ReactTestRenderer.act(() => {
            jest.advanceTimersByTime(AUTO_ADVANCE_DELAY_MS * 3);
        });

        expect(navigation.navigate).not.toHaveBeenCalled();
        expect(renderedText(renderer)).not.toContain('Continuando al minteo');
    });
});
