import { expect, test } from '@playwright/test';
import {
    E2E_FIXTURE,
    installBackendFixture,
    installEip1193Fixture,
} from './support/e2e-fixture.js';

test('simula el flujo completo de login y voto EIP-712', async ({ page }) => {
    test.slow();
    await installEip1193Fixture(page);
    const backend = await installBackendFixture(page);

    // a. Cargar la app web.
    await page.goto('/unete');
    
    // c. Firmar el challenge SIWE y completar el login. (Flujo Clave Unica)
    await page.getByRole('button', { name: 'INGRESAR CON CLAVEÚNICA', exact: true }).click();
    await page.getByRole('button', { name: 'CONTINUAR A CLAVEÚNICA', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Estado de la acreditación' })).toBeVisible();
    
    await page.getByRole('button', { name: 'CONTINUAR A LA WALLET' }).click();
    
    // b. Inyectar un proveedor Ethereum falso ya está hecho por la fixture.
    await page.getByRole('button', { name: 'CONECTAR METAMASK', exact: true }).click();
    await expect(page.getByText('WALLET CONECTADA')).toBeVisible();
    await expect(page.getByText('Verificando membresía existente...')).toBeHidden();
    
    await page.getByRole('button', { name: 'CONTINUAR', exact: true }).click();
    
    // Saltamos la creación de credencial, vamos directo a propuestas
    // Ya tenemos sesión HTTP y EIP-1193 provider.

    // d. Navegar a una propuesta y emitir un voto público firmando la papeleta EIP-712.
    await page.goto('/dashboard/propuestas');
    
    await expect(page.getByText('Presupuesto participativo — fixture E2E')).toBeVisible();
    
    // Hacer click en el botón de votar a favor
    await page.getByRole('button', { name: 'Votar A favor' }).click();
    
    // Esperar a que el botón vuelva a estar disponible
    await expect(page.getByRole('button', { name: 'Votar A favor' })).toBeEnabled();

    // Validar que el request llegó al backend
    expect(backend.publicVotes).toHaveLength(1);
    expect(backend.publicVotes[0]).toMatchObject({
        proposal_id: E2E_FIXTURE.proposalId,
        voter_address: E2E_FIXTURE.userAddress,
        vote: 'for'
    });
    expect(backend.publicVotes[0].signature).toMatch(/^0x/);
});
