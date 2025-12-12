/**
 * Animated Particles Background
 * Creates floating cyberpunk particles effect - OPTIMIZED
 */
import React, { useMemo } from 'react';

const ParticlesBackground = ({ count = 50 }) => {
    // Generate particles only once with useMemo
    const particles = useMemo(() => {
        return Array.from({ length: count }, (_, i) => {
            const size = Math.random() * 4 + 2;
            const left = Math.random() * 100;
            const delay = Math.random() * 20;
            const duration = Math.random() * 10 + 15;
            const hue = Math.random() > 0.5 ? 180 : (Math.random() > 0.5 ? 300 : 120);

            return {
                id: i,
                style: {
                    width: `${size}px`,
                    height: `${size}px`,
                    left: `${left}%`,
                    background: `hsl(${hue}, 100%, 50%)`,
                    boxShadow: `0 0 ${size * 2}px hsl(${hue}, 100%, 50%)`,
                    animationDelay: `${delay}s`,
                    animationDuration: `${duration}s`,
                }
            };
        });
    }, [count]);

    return (
        <div className="particles-container">
            {particles.map(particle => (
                <div
                    key={particle.id}
                    className="particle"
                    style={particle.style}
                />
            ))}
        </div>
    );
};

export default ParticlesBackground;
