/**
 * Holographic NFT Card Component
 * Premium 3D card with mouse-follow tilt and holographic shimmer
 */
import React, { useRef, useState } from 'react';
import { Shield, Fingerprint, Cpu } from 'lucide-react';

const HolographicCard = ({
    tokenId,
    walletAddress,
    className = ''
}) => {
    const cardRef = useRef(null);
    const [transform, setTransform] = useState({ rotateX: 0, rotateY: 0 });
    const [isHovered, setIsHovered] = useState(false);

    const handleMouseMove = (e) => {
        if (!cardRef.current) return;

        const rect = cardRef.current.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        const rotateX = ((e.clientY - centerY) / (rect.height / 2)) * -15;
        const rotateY = ((e.clientX - centerX) / (rect.width / 2)) * 15;

        setTransform({ rotateX, rotateY });
    };

    const handleMouseLeave = () => {
        setTransform({ rotateX: 0, rotateY: 0 });
        setIsHovered(false);
    };

    return (
        <div
            className={`holographic-card-container ${className}`}
            style={{ perspective: '1000px' }}
        >
            <div
                ref={cardRef}
                className="holographic-card"
                onMouseMove={handleMouseMove}
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={handleMouseLeave}
                style={{
                    transform: `rotateX(${transform.rotateX}deg) rotateY(${transform.rotateY}deg) scale(${isHovered ? 1.05 : 1})`,
                    transition: isHovered ? 'transform 0.1s ease-out' : 'transform 0.5s ease-out'
                }}
            >
                {/* Holographic shimmer overlay */}
                <div className="holographic-shimmer" />

                {/* Card content */}
                <div className="holographic-card-content">
                    {/* Header */}
                    <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center gap-2">
                            <Shield className="w-5 h-5 text-cyan-400" />
                            <span className="text-xs font-mono text-cyan-400 uppercase tracking-wider">
                                DAO Ciudadana
                            </span>
                        </div>
                        <div className="holographic-badge">
                            ZK
                        </div>
                    </div>

                    {/* NFT Icon */}
                    <div className="flex justify-center my-8">
                        <div className="holographic-icon">
                            <Fingerprint className="w-16 h-16 text-cyan-400" />
                        </div>
                    </div>

                    {/* Token ID */}
                    <div className="text-center mb-6">
                        <div className="holographic-token-id">
                            #{tokenId || '000000'}
                        </div>
                        <div className="text-xs text-gray-500 font-mono mt-1">
                            SOULBOUND TOKEN
                        </div>
                    </div>

                    {/* Footer */}
                    <div className="holographic-card-footer">
                        <div className="flex items-center gap-2">
                            <Cpu className="w-4 h-4 text-purple-400" />
                            <span className="text-xs font-mono text-gray-400 truncate max-w-[150px]">
                                {walletAddress ? `${walletAddress.slice(0, 6)}...${walletAddress.slice(-4)}` : '0x...'}
                            </span>
                        </div>
                        <div className="holographic-status">
                            ACTIVO
                        </div>
                    </div>
                </div>

                {/* Corner decorations */}
                <div className="holographic-corner top-left" />
                <div className="holographic-corner top-right" />
                <div className="holographic-corner bottom-left" />
                <div className="holographic-corner bottom-right" />
            </div>
        </div>
    );
};

export default HolographicCard;
