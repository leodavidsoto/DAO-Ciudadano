# Prompt — D-3: reconciliar el tally MACI con el contrato

> Pégale esto a un agente nuevo en `/Users/mac/DAO-Ciudadano`.
>
> **Aislamiento:** esta tarea vive en `circuits/` y `contracts/`. Los otros dos
> encargos en curso tocan `mobile/` y `backend/app/services/`. No os pisáis.

---

Lee `AGENTS.md` antes de tocar código. Trabajas en la rama `codex/produccion-ci`.

## El problema

La votación privada está anunciada como no disponible —`private_voting: false` en
`/health`— y **no es un ajuste pendiente, es un hecho**: hoy ninguna elección
puede cerrarse con prueba.

El contrato y el circuito hablan de cosas distintas.

`contracts/MACICoordinator.sol:325` arma las señales públicas así:

```solidity
uint256[3] memory publicSignals = [
    uint256(poll.messageChain) % SNARK_SCALAR_FIELD,
    poll.signUpCount,
    uint256(tallyCommitment) % SNARK_SCALAR_FIELD
];
```

`circuits/maci_tally.circom` expone:

```
[stateRoot, currentResultsCommitment, newResultsCommitment]
```

**No es un desajuste de nombres: son magnitudes distintas.** La posición `[1]`
del circuito es un Poseidon de ~254 bits; el contrato pone ahí el número de
inscritos. Ninguna prueba auténtica del circuito puede satisfacer lo que el
contrato pregunta, y ninguna consulta real puede tener tantos inscritos.

## Está ya reproducido, no empieces de cero

```bash
cd contracts && npx hardhat test test/MACI.test.js
```

El bloque `"frontera rota entre publishTally y maci_tally.circom"` (línea 264)
**afirma el fallo como test**: una prueba auténtica es rechazada por
`publishTally`. Esos tests pasan hoy porque documentan el bloqueador; cuando lo
arregles tendrás que reescribirlos para que afirmen lo contrario. Es esperado:
di explícitamente en el commit que inviertes su sentido.

También existe una tarea que lo reproduce de punta a punta y sale con estado 1:

```bash
cd contracts && npx hardhat maci:tally --network hardhat
```

## Tu tarea

Que una prueba auténtica del circuito de tally sea aceptada por `publishTally`,
sin debilitar lo que el contrato garantiza.

## La decisión de diseño (consúltala, no la tomes solo)

Esto **es** D-3 en `docs/ROADMAP.md`, y `AGENTS.md` dice que las decisiones de
arquitectura no las toma un agente solo. Hay al menos tres salidas y no son
equivalentes:

1. **Cambiar el circuito** para que exponga lo que el contrato ancla
   (`messageChain`, `signUpCount`, `tallyCommitment`). Obliga a **repetir la
   ceremonia** y a regenerar el verificador.
2. **Cambiar el contrato** para anclar lo que el circuito ya prueba
   (`stateRoot`, y los dos compromisos de resultados). Más barato, pero hay que
   demostrar que sigue atando la prueba a *esta* consulta y no a otra.
3. **Una capa de adaptación** que derive las señales del contrato desde las del
   circuito. Sospecha de esta: suele esconder que la atadura se perdió.

El comentario de `MACICoordinator.sol:308` dice por qué se eligieron esas
señales: *«Sin esa atadura, una prueba de otra consulta serviría para publicar
aquí»*. **Cualquier solución tiene que conservar esa propiedad.** Si tu diseño
permite reutilizar una prueba de otra `poll`, es incorrecto por muy verde que
esté la suite.

## Lo que ya tienes hecho

- `circuits/maci_tally.circom` y su ceremonia en
  `circuits/build/trusted-setup/tally-integracion/`.
- `contracts/TallyVerifier.sol` — verificador generado, con 6 tests que ya
  comprueban que rechaza señales alteradas, pruebas manipuladas y valores fuera
  del campo escalar.
- Un fixture de prueba auténtica que valida con snarkjs.
- `contracts/tasks/maci-tally.js` — simula el recuento completo.

## Aviso importante sobre los tests

Este mes cayeron dos supuestos que llevaban meses en verde: P-97 (el formato del
CAN) y P-101 (la posición del RUN dentro de la MRZ). En ambos casos **el fixture
reproducía el error en lugar de detectarlo**, así que cientos de tests verdes no
vieron nada.

Aquí el riesgo es idéntico: si generas el fixture de prueba con la misma
suposición con la que escribes el contrato, la suite quedará verde y seguirá sin
funcionar contra una ceremonia real. Genera la prueba con **snarkjs desde el
circuito compilado**, no a mano.

## Reglas que no puedes saltarte

- `AGENTS.md` regla 6: **todo cambio en `contracts/` necesita tests antes del
  merge. Sin excepción** — es un contrato de identidad civil.
- Regla 5: no simules capacidades que no existen. Si tras tu cambio la votación
  privada sigue sin ser privada, `private_voting` debe seguir en `false`.
- Regla 3: no marques nada completo sin ejecutar el camino real.
- Errores personalizados en vez de strings de revert (Solidity 0.8.20, OZ 5).
- Todo hallazgo nuevo va a `docs/AUDIT.md` con `archivo:línea` y severidad.

## Criterios de aceptación

1. `npx hardhat maci:tally` completa el recuento y **sale con estado 0**.
2. Una prueba auténtica generada por snarkjs es aceptada por `publishTally`.
3. Una prueba de **otra** consulta sigue siendo rechazada — con un test que lo
   demuestre. Es la propiedad que no se puede perder.
4. Los tests del bloque «frontera rota» quedan invertidos: ahora afirman que la
   frontera cierra.
5. `cd contracts && npx hardhat test` en verde (hoy: 59 tests).
6. Si hiciste falta repetir la ceremonia, queda documentado quién participó y
   cómo se verifica — una ceremonia de una sola parte no es una ceremonia, y
   `docs/ROADMAP.md` ya la tiene marcada como pendiente.

## Si resulta que no se puede cerrar

Es un resultado legítimo y quiero saberlo pronto. Documenta en `docs/AUDIT.md`
qué exige exactamente, con números: cuántas restricciones, qué ceremonia, qué
coste de gas. No dejes `private_voting: true` con una implementación a medias.
