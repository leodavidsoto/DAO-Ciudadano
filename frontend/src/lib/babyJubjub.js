// The package publishes both ESM and CJS. CRA's Jest resolver selects the ESM
// entry without transforming node_modules, so this narrow CommonJS bridge keeps
// browser and test resolution consistent.
const babyJubjub = require('@zk-kit/baby-jubjub');

export const Base8 = babyJubjub.Base8;
export const inCurve = babyJubjub.inCurve;
export const mulPointEscalar = babyJubjub.mulPointEscalar;
export const r = babyJubjub.r;
export const subOrder = babyJubjub.subOrder;
