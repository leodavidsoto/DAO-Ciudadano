/**
 * MembershipQR Component
 * Generates a scannable QR code for membership verification
 */
import React, { useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { Download, Share2, QrCode, Shield, Copy, Check } from 'lucide-react';
import { Button } from '../ui/button';

const MembershipQR = ({
    tokenId,
    walletAddress,
    assuranceLevel = 'AL1',
    memberName = null
}) => {
    const [copied, setCopied] = useState(false);
    const [showFullscreen, setShowFullscreen] = useState(false);

    // Point to a real backend verification endpoint. The previous payload was
    // self-asserted JSON and linked to a frontend route that did not exist.
    const backendUrl = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';
    const verificationUrl = `${backendUrl}/api/membership/verify/${tokenId}`;

    const handleCopy = () => {
        navigator.clipboard.writeText(verificationUrl);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
    };

    const handleDownload = () => {
        const svg = document.getElementById('membership-qr-svg');
        if (!svg) return;

        const svgData = new XMLSerializer().serializeToString(svg);
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const img = new Image();

        img.onload = () => {
            canvas.width = 400;
            canvas.height = 400;
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, 400, 400);
            ctx.drawImage(img, 50, 50, 300, 300);

            const link = document.createElement('a');
            link.download = `dao-ciudadana-${tokenId}.png`;
            link.href = canvas.toDataURL('image/png');
            link.click();
        };

        img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
    };

    const handleShare = async () => {
        if (navigator.share) {
            try {
                await navigator.share({
                    title: 'Consulta de membresía DAO Ciudadana',
                    text: `Consulta el estado de la credencial #${tokenId}`,
                    url: verificationUrl,
                });
            } catch (err) {
                console.log('Share cancelled');
            }
        } else {
            handleCopy();
        }
    };

    return (
        <>
            <div className="membership-qr civic-card civic-card-pad text-center">
                {/* Header */}
                <div className="flex items-center justify-center gap-2 mb-4">
                    <QrCode className="w-5 h-5" style={{ color: '#003897' }} />
                    <h3 className="civic-ink font-bold" style={{ fontFamily: 'Poppins, sans-serif' }}>
                        Credencial digital
                    </h3>
                </div>

                {/* QR Code Container */}
                <div
                    className="qr-container relative inline-block p-4 bg-white rounded-lg cursor-pointer hover:scale-105 transition-transform"
                    style={{ border: '1px solid #E5EBF5' }}
                    onClick={() => setShowFullscreen(true)}
                >
                    <QRCodeSVG
                        id="membership-qr-svg"
                        value={verificationUrl}
                        size={180}
                        level="H"
                        includeMargin={false}
                        bgColor="#ffffff"
                        fgColor="#0B2545"
                    />

                    {/* Center logo overlay */}
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div
                            className="w-10 h-10 bg-white rounded-lg flex items-center justify-center"
                            style={{ border: '2px solid #003897' }}
                        >
                            <Shield className="w-6 h-6" style={{ color: '#003897' }} />
                        </div>
                    </div>
                </div>

                {/* Token Info */}
                <div className="mt-4 space-y-1">
                    <div className="civic-stat-value" style={{ color: '#003897' }}>
                        #{tokenId}
                    </div>
                    {memberName && (
                        <div className="civic-ink font-medium">{memberName}</div>
                    )}
                    <div className="civic-mono civic-muted">
                        {walletAddress?.slice(0, 8)}…{walletAddress?.slice(-6)}
                    </div>
                    <div>
                        <span className="civic-tag civic-tag-blue">Nivel {assuranceLevel}</span>
                    </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2 mt-4 justify-center">
                    <Button
                        onClick={handleCopy}
                        variant="outline"
                        size="sm"
                        className="civic-btn civic-btn-sm civic-btn-quiet"
                        aria-label="Copiar enlace de verificación"
                    >
                        {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </Button>
                    <Button
                        onClick={handleDownload}
                        variant="outline"
                        size="sm"
                        className="civic-btn civic-btn-sm civic-btn-quiet"
                        aria-label="Descargar el código QR"
                    >
                        <Download className="w-4 h-4" />
                    </Button>
                    <Button
                        onClick={handleShare}
                        variant="outline"
                        size="sm"
                        className="civic-btn civic-btn-sm civic-btn-quiet"
                        aria-label="Compartir la credencial"
                    >
                        <Share2 className="w-4 h-4" />
                    </Button>
                </div>

                <p className="civic-faint text-xs mt-3">
                    Escanea para consultar el estado de la credencial
                </p>
            </div>

            {/* Fullscreen Modal */}
            {showFullscreen && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-8"
                    style={{ background: 'rgba(11, 37, 69, 0.85)' }}
                    onClick={() => setShowFullscreen(false)}
                >
                    <div className="bg-white p-8 rounded-2xl">
                        <QRCodeSVG
                            value={verificationUrl}
                            size={300}
                            level="H"
                            includeMargin={true}
                            bgColor="#ffffff"
                            fgColor="#0a0a0f"
                        />
                        <div className="text-center mt-4 font-bold" style={{ color: '#0B2545' }}>
                            Token #{tokenId}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default MembershipQR;
