import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';

export function usePageTracking() {
    const location = useLocation();

    useEffect(() => {
        const trackVisit = async () => {
            try {
                await axios.post(`${BACKEND_URL}/api/metrics/visit`, {
                    path: location.pathname,
                    user_agent: navigator.userAgent,
                    referrer: document.referrer
                });
            } catch (error) {
                // Silently fail if analytics tracking fails, we don't want to disrupt user experience
                console.error("Tracking error", error);
            }
        };

        trackVisit();
    }, [location.pathname]);
}
