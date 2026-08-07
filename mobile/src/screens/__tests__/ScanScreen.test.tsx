jest.mock('react-native-quick-crypto', () => require('crypto'));

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { TextInput, TouchableOpacity } from 'react-native';
import NfcManager from 'react-native-nfc-manager';
import ScanScreen from '../ScanScreen';
import nfcService, { type NFCReadResult } from '../../services/nfcService';

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
    let renderer!: ReactTestRenderer.ReactTestRenderer;
    await ReactTestRenderer.act(async () => {
        renderer = ReactTestRenderer.create(<ScanScreen navigation={navigation} />);
    });
    mounted.push(renderer);
    return { renderer, navigation };
}

async function typeCan(renderer: ReactTestRenderer.ReactTestRenderer, value: string) {
    await ReactTestRenderer.act(async () => {
        renderer.root.findByType(TextInput).props.onChangeText(value);
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

    it('asks for the six-digit CAN, not the document number', async () => {
        const { renderer } = await renderScreen();
        const text = renderedText(renderer);

        expect(text).toContain('Card Access Number (CAN)');
        expect(text).toContain('No es el RUT ni el número de documento.');
        expect(renderer.root.findByType(TextInput).props.maxLength).toBe(6);
        expect(renderer.root.findByType(TextInput).props.keyboardType).toBe('number-pad');
    });

    it('strips non-digits and caps input at six characters', async () => {
        const { renderer } = await renderScreen();
        await typeCan(renderer, 'A1b2-3 4567890');

        expect(renderer.root.findByType(TextInput).props.value).toBe('123456');
    });

    it('keeps the scan button disabled until the CAN is complete', async () => {
        const { renderer } = await renderScreen();
        const scanButton = () => renderer.root.findAllByType(TouchableOpacity)[0];

        expect(scanButton().props.disabled).toBe(true);
        await typeCan(renderer, '12345');
        expect(scanButton().props.disabled).toBe(true);
        await typeCan(renderer, '123456');
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
        expect(text).toMatch(/más frecuente es un CAN equivocado/i);
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
