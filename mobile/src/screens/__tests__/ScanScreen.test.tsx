jest.mock('react-native-quick-crypto', () => require('crypto'));

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { TextInput, TouchableOpacity } from 'react-native';
import NfcManager from 'react-native-nfc-manager';
import ScanScreen from '../ScanScreen';
import apiService from '../../services/apiService';
import {
    OnboardingProvider,
    useOnboarding,
    type OnboardingContextValue,
} from '../../context/OnboardingContext';
import nfcService, {
    parseNativePassportReadResult,
    PACE_CAN_MAX_LENGTH,
    type NFCReadResult,
    type VerifiedNFCReadResult,
} from '../../services/nfcService';

/** A reading that passes every local gate, raw files included. */
function verifiedRead(): VerifiedNFCReadResult {
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

/** Shapes an axios rejection the way the screen inspects it. */
function serverRejection(status: number, detail: unknown) {
    return Object.assign(new Error(`Request failed with status code ${status}`), {
        response: { status, data: { detail } },
    });
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

// Mounted trees are torn down between tests: a leaked ScanScreen keeps its
// pulse animation and NFC effect alive, and every later `act()` flushes them
// too, which is enough to blow the default timeout.
const mounted: ReactTestRenderer.ReactTestRenderer[] = [];

async function unmountAll() {
    await ReactTestRenderer.act(async () => {
        while (mounted.length) mounted.pop()?.unmount();
    });
}

/** Renders with NFC reported as available so the scan button is reachable. */
async function renderScreen() {
    (NfcManager.isSupported as jest.Mock).mockResolvedValue(true);
    (NfcManager.isEnabled as jest.Mock).mockResolvedValue(true);

    const navigation = { navigate: jest.fn() };
    // Reads the same context the screen writes to, so a test can check what
    // was actually stored instead of only what was navigated with.
    let context: OnboardingContextValue | null = null;
    const Probe: React.FC = () => {
        context = useOnboarding();
        return null;
    };

    let renderer!: ReactTestRenderer.ReactTestRenderer;
    await ReactTestRenderer.act(async () => {
        renderer = ReactTestRenderer.create(
            <OnboardingProvider>
                <ScanScreen navigation={navigation} />
                <Probe />
            </OnboardingProvider>,
        );
    });
    mounted.push(renderer);
    return { renderer, navigation, onboarding: () => context };
}

/**
 * El primero de los tres campos es el número de documento; los otros dos son
 * las fechas. `findByType` ya no sirve: lanzaría por ambigüedad.
 */
function canInput(renderer: ReactTestRenderer.ReactTestRenderer) {
    return renderer.root.findAllByType(TextInput)[0];
}

async function typeCan(renderer: ReactTestRenderer.ReactTestRenderer, value: string) {
    await ReactTestRenderer.act(async () => {
        canInput(renderer).props.onChangeText(value);
    });
}

async function pressScan(renderer: ReactTestRenderer.ReactTestRenderer) {
    await ReactTestRenderer.act(async () => {
        renderer.root.findAllByType(TouchableOpacity)[0].props.onPress();
    });
}

describe('ScanScreen CAN entry', () => {
    afterEach(async () => {
        await unmountAll();
        jest.restoreAllMocks();
    });

    it('asks for the printed document number, and warns it is not the RUT', async () => {
        const { renderer } = await renderScreen();
        const text = renderedText(renderer);

        // El RUT es el error clásico: está impreso más grande y más arriba que
        // el número de documento.
        expect(text).toMatch(/no uses tu rut/i);
        expect(canInput(renderer).props.maxLength).toBe(PACE_CAN_MAX_LENGTH);
    });

    it('strips punctuation, upper-cases and caps input at the native limit', async () => {
        const { renderer } = await renderScreen();
        await typeCan(renderer, 'a12-345 678');

        expect(canInput(renderer).props.value).toBe('A12345678');

        await typeCan(renderer, '1234567890123456789');
        expect(canInput(renderer).props.value).toHaveLength(PACE_CAN_MAX_LENGTH);
    });

    it('keeps the scan button disabled until the document number is long enough', async () => {
        const { renderer } = await renderScreen();
        const scanButton = () => renderer.root.findAllByType(TouchableOpacity)[0];

        expect(scanButton().props.disabled).toBe(true);
        await typeCan(renderer, '12345');
        expect(scanButton().props.disabled).toBe(true);
        await typeCan(renderer, 'A12345678');
        expect(scanButton().props.disabled).toBe(false);
    });
});

describe('ScanScreen secure-channel failures', () => {
    afterEach(async () => {
        await unmountAll();
        jest.restoreAllMocks();
    });

    it('guides the citizen to the CAN when PACE rejects the key', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue({
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            errorCode: 'E_PACE_FAILED',
            error: 'PACE rechazado por el chip',
        } as NFCReadResult);

        const { renderer, navigation } = await renderScreen();
        await typeCan(renderer, '999999');
        await pressScan(renderer);

        const text = renderedText(renderer);
        expect(text).toContain('No se pudo abrir el canal seguro');
        expect(text).toMatch(/revisa el número de documento/i);
        // The native detail stays visible as evidence, not as the headline.
        expect(text).toContain('PACE rechazado por el chip');
        expect(navigation.navigate).not.toHaveBeenCalled();
    });

    it('clears wrong-CAN guidance as soon as the citizen edits the field', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue({
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            errorCode: 'E_PACE_FAILED',
            error: 'PACE rechazado por el chip',
        } as NFCReadResult);

        const { renderer } = await renderScreen();
        await typeCan(renderer, '999999');
        await pressScan(renderer);
        expect(renderedText(renderer)).toContain('No se pudo abrir el canal seguro');

        await typeCan(renderer, '123456');
        expect(renderedText(renderer)).not.toContain('No se pudo abrir el canal seguro');
    });

    it('does not blame the citizen when the build has no CSCA chain', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue({
            status: 'failed',
            readCompleted: false,
            identityVerified: false,
            errorCode: 'E_CSCA_MASTER_LIST_MISSING',
            error: 'Master List ausente',
        } as NFCReadResult);

        const { renderer } = await renderScreen();
        await typeCan(renderer, '123456');
        await pressScan(renderer);

        expect(renderedText(renderer)).toMatch(/no es un problema de tu cédula/i);
    });

    it('never navigates to Success on a read that completed but did not verify', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue({
            status: 'read_unverified',
            readCompleted: true,
            identityVerified: false,
            error: 'La firma de EF.SOD no es válida.',
        } as NFCReadResult);

        const { renderer, navigation } = await renderScreen();
        await typeCan(renderer, '123456');
        await pressScan(renderer);

        expect(navigation.navigate).not.toHaveBeenCalled();
        expect(renderedText(renderer)).toContain('La cédula se leyó, pero no se verificó');
    });
});

describe('ScanScreen server enrolment', () => {
    afterEach(async () => {
        await unmountAll();
        jest.restoreAllMocks();
    });

    async function scanVerified(renderer: ReactTestRenderer.ReactTestRenderer) {
        await typeCan(renderer, '123456');
        await pressScan(renderer);
    }

    it('sends the raw chip files and keeps the grants the server returns', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue(verifiedRead());
        const verify = jest.spyOn(apiService, 'verifyCedula').mockResolvedValue({
            ok: true,
            identity_grant: 'identity.grant.jwt',
            identity_grant_expires_in: 300,
            membership_grant: 'membership.grant.jwt',
            membership_grant_expires_in: 900,
            assurance_level: 'CEDULA_NFC_PASSIVE',
            verification: {},
        });

        const { renderer, navigation, onboarding } = await renderScreen();
        await scanVerified(renderer);

        // Bytes, never this device's verdict: the server re-runs passive
        // authentication and only then may issue a credential.
        expect(verify).toHaveBeenCalledWith({ sod: 'RUYuU09E', dg1: 'REcx', dg2: 'REcy' });

        const grants = onboarding()?.grants;
        expect(grants?.membershipGrant).toBe('membership.grant.jwt');
        expect(grants?.assuranceLevel).toBe('CEDULA_NFC_PASSIVE');
        expect(onboarding()?.hasUsableGrant()).toBe(true);

        expect(navigation.navigate).toHaveBeenCalledWith(
            'Success',
            expect.objectContaining({ grantIssued: true }),
        );
    });

    it('does not enrol when the server rejects the reading', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue(verifiedRead());
        jest.spyOn(apiService, 'verifyCedula').mockRejectedValue(
            serverRejection(401, { reasons: ['La firma de EF.SOD no es válida.'] }),
        );

        const { renderer, navigation, onboarding } = await renderScreen();
        await scanVerified(renderer);

        const text = renderedText(renderer);
        expect(text).toContain('El servidor rechazó la cédula');
        // The server's own reasons are shown, not a paraphrase of them.
        expect(text).toContain('La firma de EF.SOD no es válida.');
        expect(navigation.navigate).not.toHaveBeenCalled();
        expect(onboarding()?.grants).toBeNull();
    });

    it('does not blame the citizen when the server has no CSCA anchors', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue(verifiedRead());
        jest.spyOn(apiService, 'verifyCedula').mockRejectedValue(
            serverRejection(503, 'Trust store vacío'),
        );

        const { renderer, navigation } = await renderScreen();
        await scanVerified(renderer);

        expect(renderedText(renderer)).toMatch(/no es un problema de tu cédula/i);
        expect(navigation.navigate).not.toHaveBeenCalled();
    });

    it('offers a retry when the server is unreachable, without discarding the read', async () => {
        jest.spyOn(nfcService, 'readChileanIDPACE').mockResolvedValue(verifiedRead());
        jest.spyOn(apiService, 'verifyCedula').mockRejectedValue(new Error('Network Error'));

        const { renderer, navigation, onboarding } = await renderScreen();
        await scanVerified(renderer);

        const text = renderedText(renderer);
        expect(text).toContain('No se pudo contactar al servidor');
        expect(text).toMatch(/La cédula se leyó correctamente/i);
        expect(navigation.navigate).not.toHaveBeenCalled();
        expect(onboarding()?.grants).toBeNull();
    });
});
