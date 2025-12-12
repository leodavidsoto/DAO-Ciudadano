/**
 * useSBTContract Hook - Interact with DAOCiudadanaSBT smart contract
 */
import { useState, useCallback } from 'react';
import { Contract } from 'ethers';
import { SBT_CONTRACT_ABI, SBT_CONTRACT_ADDRESSES } from '@/contracts/SBTContract';

const useSBTContract = (signer, chainId) => {
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);

    // Get contract address for current chain
    const contractAddress = chainId ? SBT_CONTRACT_ADDRESSES[chainId] : null;

    // Get contract instance
    const getContract = useCallback(() => {
        if (!signer || !contractAddress) {
            return null;
        }
        return new Contract(contractAddress, SBT_CONTRACT_ABI, signer);
    }, [signer, contractAddress]);

    // Check if address has membership
    const hasMembership = useCallback(async (address) => {
        const contract = getContract();
        if (!contract) return false;

        try {
            return await contract.hasMembership(address);
        } catch (err) {
            console.error('hasMembership error:', err);
            return false;
        }
    }, [getContract]);

    // Get membership token ID
    const getMembershipToken = useCallback(async (address) => {
        const contract = getContract();
        if (!contract) return null;

        try {
            const tokenId = await contract.getMembershipToken(address);
            return tokenId.toString();
        } catch (err) {
            console.error('getMembershipToken error:', err);
            return null;
        }
    }, [getContract]);

    // Get total supply
    const getTotalSupply = useCallback(async () => {
        const contract = getContract();
        if (!contract) return 0;

        try {
            const supply = await contract.totalSupply();
            return parseInt(supply.toString());
        } catch (err) {
            console.error('getTotalSupply error:', err);
            return 0;
        }
    }, [getContract]);

    // Mint membership (requires owner/backend signature in production)
    // This is a simplified version - in production, backend would sign the transaction
    const mintMembership = useCallback(async (to, identityHash, assuranceLevel, tokenUri) => {
        const contract = getContract();
        if (!contract) {
            return { ok: false, error: 'Contract not available on this network' };
        }

        setIsLoading(true);
        setError(null);

        try {
            const tx = await contract.mintMembership(to, identityHash, assuranceLevel, tokenUri);
            console.log('Mint transaction sent:', tx.hash);

            const receipt = await tx.wait();
            console.log('Mint confirmed:', receipt);

            // Extract token ID from events
            const event = receipt.logs.find(log => {
                try {
                    const parsed = contract.interface.parseLog(log);
                    return parsed.name === 'MembershipMinted';
                } catch {
                    return false;
                }
            });

            let tokenId = null;
            if (event) {
                const parsed = contract.interface.parseLog(event);
                tokenId = parsed.args.tokenId.toString();
            }

            return {
                ok: true,
                txHash: receipt.hash,
                tokenId,
                blockNumber: receipt.blockNumber,
            };
        } catch (err) {
            console.error('Mint error:', err);
            const errorMessage = err.reason || err.message || 'Error minting SBT';
            setError(errorMessage);
            return { ok: false, error: errorMessage };
        } finally {
            setIsLoading(false);
        }
    }, [getContract]);

    return {
        // State
        isLoading,
        error,
        contractAddress,
        isContractAvailable: !!contractAddress,

        // Actions
        hasMembership,
        getMembershipToken,
        getTotalSupply,
        mintMembership,

        // Contract instance
        getContract,
    };
};

export default useSBTContract;
