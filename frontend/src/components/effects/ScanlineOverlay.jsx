/**
 * Scanline Overlay Effect
 * Adds retro CRT scanline effect
 */
import React from 'react';

const ScanlineOverlay = ({ opacity = 0.1 }) => (
    <div
        className="scanline-overlay"
        style={{ opacity }}
        aria-hidden="true"
    />
);

export default ScanlineOverlay;
