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

    // Generate verification URL
    const verificationUrl = `${window.location.origin}/verify/${tokenId}`;

    // QR data payload
    const qrData = JSON.stringify({
        type: 'dao_ciudadana_member',
        tokenId,
        wallet: walletAddress?.slice(0, 10) + '...',
        level: assuranceLevel,
        v: 1, // version
    });

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
            ctx.fillStyle = '#0a0a0f';
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
                    title: 'Mi Membresía DAO Ciudadana',
                    text: `Soy miembro verificado de DAO Ciudadana. Token #${tokenId}`,
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
            <div className="membership-qr glass-dark rounded-xl p-6 text-center">
                {/* Header */}
                <div className="flex items-center justify-center gap-2 mb-4">
                    <QrCode className="w-5 h-5 text-cyan-400" />
                    <h3 className="font-bold text-white">Credencial Digital</h3>
                </div>

                {/* QR Code Container */}
                <div
                    className="qr-container relative inline-block p-4 bg-white rounded-lg cursor-pointer hover:scale-105 transition-transform"
                    onClick={() => setShowFullscreen(true)}
                >
                    <QRCodeSVG
                        id="membership-qr-svg"
                        value={qrData}
                        size={180}
                        level="H"
                        includeMargin={false}
                        bgColor="#ffffff"
                        fgColor="#0a0a0f"
                    />

                    {/* Center logo overlay */}
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div className="w-10 h-10 bg-white rounded-lg flex items-center justify-center border-2 border-cyan-500">
                            <Shield className="w-6 h-6 text-cyan-600" />
                        </div>
                    </div>
                </div>

                {/* Token Info */}
                <div className="mt-4 space-y-1">
                    <div className="text-2xl font-bold text-cyan-400 font-mono">
                        #{tokenId}
                    </div>
                    {memberName && (
                        <div className="text-white font-medium">{memberName}</div>
                    )}
                    <div className="text-xs text-gray-400 font-mono">
                        {walletAddress?.slice(0, 8)}...{walletAddress?.slice(-6)}
                    </div>
                    <div className="inline-block px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded-full border border-green-500/30">
                        Nivel {assuranceLevel}
                    </div>
                </div>

                {/* Action Buttons */}
                <div className="flex gap-2 mt-4 justify-center">
                    <Button
                        onClick={handleCopy}
                        variant="outline"
                        size="sm"
                        className="border-gray-600 text-gray-400 hover:text-cyan-400"
                    >
                        {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </Button>
                    <Button
                        onClick={handleDownload}
                        variant="outline"
                        size="sm"
                        className="border-gray-600 text-gray-400 hover:text-cyan-400"
                    >
                        <Download className="w-4 h-4" />
                    </Button>
                    <Button
                        onClick={handleShare}
                        variant="outline"
                        size="sm"
                        className="border-gray-600 text-gray-400 hover:text-cyan-400"
                    >
                        <Share2 className="w-4 h-4" />
                    </Button>
                </div>

                <p className="text-xs text-gray-500 mt-3">
                    Escanea para verificar autenticidad
                </p>
            </div>

            {/* Fullscreen Modal */}
            {showFullscreen && (
                <div
                    className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-8"
                    onClick={() => setShowFullscreen(false)}
                >
                    <div className="bg-white p-8 rounded-2xl">
                        <QRCodeSVG
                            value={qrData}
                            size={300}
                            level="H"
                            includeMargin={true}
                            bgColor="#ffffff"
                            fgColor="#0a0a0f"
                        />
                        <div className="text-center mt-4 text-black font-bold">
                            Token #{tokenId}
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default MembershipQR;
