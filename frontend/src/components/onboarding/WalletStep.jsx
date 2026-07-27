/**
 * Wallet Connection Step - Real MetaMask Integration
 */
import React, { useState, useEffect } from 'react';
import { Wallet, Globe, AlertCircle, ExternalLink, RefreshCw, Loader2, ArrowRight } from 'lucide-react';
import { Button } from '../ui/button';
import { Badge } from '../ui/badge';
import { CyberPanel, CyberLoader, SuccessDisplay } from './CyberUI';
import { useOnboarding } from '@/context';
import { useWallet } from '@/hooks';

const WalletStep = () => {
    const { setWallet, setStep, wallet: onboardingWallet } = useOnboarding();
    const {
        connect,
        address,
        balance,
        chainId,
        networkInfo,
        shortAddress,
        isConnecting,
        error,
        isMetaMaskInstalled,
        isConnected,
        switchNetwork
    } = useWallet();

    const [isChecking, setIsChecking] = useState(true);

    // Chain the SBT contract is deployed on (see frontend/src/contracts/SBTContract.js)
    const REQUIRED_CHAIN_ID = 11155111; // Sepolia
    const isWrongNetwork = isConnected && chainId != null && Number(chainId) !== REQUIRED_CHAIN_ID;

    const goToMint = () => {
        setWallet({ address, chainId });
        setStep('mint');
    };

    // MetaMask may already be authorized for this site, in which case useWallet
    // reconnects on mount and handleConnect never runs. Without this effect the
    // flow renders "WALLET CONECTADA" and stops there forever.
    useEffect(() => {
        if (!isConnected || !address) return;
        if (onboardingWallet.address === address) return;
        setWallet({ address, chainId });
    }, [isConnected, address, chainId, onboardingWallet.address, setWallet]);

    // Give time for MetaMask detection
    useEffect(() => {
        const timer = setTimeout(() => {
            setIsChecking(false);
        }, 1000);
        return () => clearTimeout(timer);
    }, []);

    const handleConnect = async () => {
        const result = await connect();
        if (result.ok) {
            // Update onboarding context with real wallet data
            setWallet({
                address: result.address,
                chainId: result.chainId,
            });
            // Auto advance to next step
            setTimeout(() => setStep('mint'), 1500);
        }
    };

    const handleRetryDetection = () => {
        setIsChecking(true);
        setTimeout(() => setIsChecking(false), 1000);
    };

    // Already connected from context (mock or previous connection)
    const walletConnected = isConnected || onboardingWallet.address;
    const displayAddress = address || onboardingWallet.address;

    return (
        <CyberPanel
            title="CONEXIÓN DE WALLET BLOCKCHAIN"
            description="Estableciendo enlace con billetera digital descentralizada"
            icon={<Wallet className="h-8 w-8" />}
        >
            <div className="flex flex-col items-center gap-6">
                {/* Checking for MetaMask */}
                {isChecking && !walletConnected && (
                    <div className="text-center p-6">
                        <Loader2 className="w-12 h-12 mx-auto text-cyan-400 mb-3 animate-spin" />
                        <p className="text-sm text-gray-400 font-mono">
                            Detectando MetaMask...
                        </p>
                    </div>
                )}

                {/* MetaMask not installed warning */}
                {!isChecking && !isMetaMaskInstalled && !walletConnected && (
                    <div className="text-center p-6 border border-yellow-500/30 rounded-lg bg-yellow-500/5">
                        <AlertCircle className="w-12 h-12 mx-auto text-yellow-400 mb-3" />
                        <h3 className="text-yellow-400 font-bold mb-2">MetaMask No Detectado</h3>
                        <p className="text-sm text-gray-400 font-mono mb-4">
                            Necesitas MetaMask para conectar tu wallet
                        </p>
                        <div className="flex flex-col gap-3">
                            <a
                                href="https://metamask.io/download/"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center justify-center gap-2 text-cyan-400 hover:text-cyan-300 font-mono text-sm border border-cyan-500/30 rounded px-4 py-2"
                            >
                                Instalar MetaMask
                                <ExternalLink className="w-4 h-4" />
                            </a>
                            <Button
                                onClick={handleRetryDetection}
                                variant="ghost"
                                className="text-gray-400 text-sm"
                            >
                                <RefreshCw className="w-4 h-4 mr-2" />
                                Ya lo tengo instalado, reintentar
                            </Button>
                        </div>
                    </div>
                )}

                {/* Connect button */}
                {!isChecking && isMetaMaskInstalled && !walletConnected && !isConnecting && (
                    <div className="text-center">
                        <div className="w-32 h-32 mx-auto mb-4 border-2 border-purple-500 rounded-lg flex items-center justify-center bg-purple-500/5 hover-glow transition-all">
                            <Globe className="w-12 h-12 text-purple-400" />
                        </div>
                        <Button onClick={handleConnect} className="cyber-button-premium">
                            <Wallet className="w-4 h-4 mr-2" />
                            CONECTAR METAMASK
                        </Button>
                        <p className="text-xs text-gray-500 mt-3 font-mono">
                            Se abrirá MetaMask para aprobar la conexión
                        </p>
                    </div>
                )}

                {/* Loading state */}
                {isConnecting && (
                    <CyberLoader text="ESPERANDO APROBACIÓN EN METAMASK..." />
                )}

                {/* Error display */}
                {error && (
                    <div className="cyber-error flex items-center gap-2">
                        <AlertCircle className="w-4 h-4" />
                        {error}
                        <Button
                            onClick={handleConnect}
                            variant="ghost"
                            size="sm"
                            className="ml-2 text-cyan-400"
                        >
                            <RefreshCw className="w-4 h-4" />
                        </Button>
                    </div>
                )}

                {/* Success state */}
                {walletConnected && (
                    <SuccessDisplay>
                        <p className="font-mono mb-2">WALLET CONECTADA</p>
                        <Badge className="cyber-badge success font-mono text-xs">
                            {shortAddress || displayAddress?.slice(0, 10) + '...' + displayAddress?.slice(-4)}
                        </Badge>
                        {networkInfo && (
                            <p className="text-xs text-gray-400 mt-2 font-mono">
                                Red: {networkInfo.name}
                            </p>
                        )}
                        {balance && (
                            <p className="text-xs text-cyan-400 mt-1 font-mono">
                                Balance: {parseFloat(balance).toFixed(4)} ETH
                            </p>
                        )}

                        {isWrongNetwork && (
                            <div className="mt-4 p-3 rounded-lg border border-yellow-500/40 bg-yellow-500/10 text-left">
                                <p className="text-yellow-300 text-xs font-mono mb-2">
                                    El contrato SBT vive en Sepolia. Cambia de red para continuar.
                                </p>
                                <Button
                                    onClick={() => switchNetwork(REQUIRED_CHAIN_ID)}
                                    className="cyber-button w-full"
                                >
                                    CAMBIAR A SEPOLIA
                                </Button>
                            </div>
                        )}

                        <Button
                            onClick={goToMint}
                            disabled={isWrongNetwork}
                            className="cyber-button-premium mt-5 w-full group"
                        >
                            CONTINUAR
                            <ArrowRight className="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" />
                        </Button>
                    </SuccessDisplay>
                )}
            </div>
        </CyberPanel>
    );
};

export default WalletStep;
