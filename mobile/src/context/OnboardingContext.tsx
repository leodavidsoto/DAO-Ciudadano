/**
 * Onboarding state for the civil enrolment flow.
 *
 * Holds the grants the backend issues after it re-verifies a cédula reading.
 * Plain React Context on purpose: `AGENTS.md` rules out Redux and Zustand, and
 * the web frontend models the same flow with its own OnboardingContext.
 *
 * Deliberately in memory only — never Keychain, never AsyncStorage. These are
 * short-lived single-use JWTs (minutes), and the mint endpoint burns the
 * membership grant on success. Persisting them would leave a credential on
 * disk that outlives the flow it belongs to, for no benefit: if the app dies
 * mid-enrolment the citizen re-scans, which is cheap.
 */

import React, {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useState,
} from 'react';
import type { ChileanIDData } from '../services/nfcService';

export interface IdentityGrants {
    identityGrant: string;
    membershipGrant: string;
    assuranceLevel: string;
    /** Epoch millis after which the membership grant is worthless. */
    membershipGrantExpiresAt: number;
}

interface OnboardingState {
    grants: IdentityGrants | null;
    /** DG1 fields, only for display. Never sent anywhere. */
    idData: ChileanIDData | null;
}

export interface OnboardingContextValue extends OnboardingState {
    hasUsableGrant: (now?: number) => boolean;
    setVerifiedIdentity: (grants: IdentityGrants, idData: ChileanIDData) => void;
    clearOnboarding: () => void;
}

const EMPTY_STATE: OnboardingState = { grants: null, idData: null };

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export const OnboardingProvider: React.FC<{ children: React.ReactNode }> = ({
    children,
}) => {
    const [state, setState] = useState<OnboardingState>(EMPTY_STATE);

    const setVerifiedIdentity = useCallback(
        (grants: IdentityGrants, idData: ChileanIDData) => {
            setState({ grants, idData });
        },
        [],
    );

    const clearOnboarding = useCallback(() => setState(EMPTY_STATE), []);

    // An expired grant is treated as absent: the mint endpoint would reject it
    // with 403 anyway, and showing "ready to mint" over a dead token sends the
    // citizen into a failure we can see coming.
    const hasUsableGrant = useCallback(
        (now: number = Date.now()) =>
            state.grants !== null && state.grants.membershipGrantExpiresAt > now,
        [state.grants],
    );

    const value = useMemo<OnboardingContextValue>(
        () => ({ ...state, hasUsableGrant, setVerifiedIdentity, clearOnboarding }),
        [state, hasUsableGrant, setVerifiedIdentity, clearOnboarding],
    );

    return (
        <OnboardingContext.Provider value={value}>
            {children}
        </OnboardingContext.Provider>
    );
};

export function useOnboarding(): OnboardingContextValue {
    const context = useContext(OnboardingContext);
    if (!context) {
        throw new Error('useOnboarding must be used inside an OnboardingProvider');
    }
    return context;
}

export default OnboardingContext;
