#!/bin/bash
TARGET="0x118d2C9eec35bdfc2C84B5A33299AcCc16Ed60d4"
MIN_BAL=5906570646860208
echo "Monitoreando balance de $TARGET en Sepolia..."
while true; do
  RES=$(curl -s -X POST https://ethereum-sepolia-rpc.publicnode.com -H 'Content-Type: application/json' -d "{\"jsonrpc\":\"2.0\",\"method\":\"eth_getBalance\",\"params\":[\"$TARGET\", \"latest\"],\"id\":1}")
  HEX_BAL=$(echo $RES | grep -o '"result":"[^"]*"' | cut -d'"' -f4)
  if [ "$HEX_BAL" != "" ]; then
    DEC_BAL=$((16#${HEX_BAL#0x}))
    if [ "$DEC_BAL" -ge "$MIN_BAL" ]; then
      echo "Fondos recibidos ($DEC_BAL wei). Iniciando despliegue..."
      cd contracts && npx hardhat run scripts/deploy.js --network sepolia
      break
    fi
  fi
  sleep 15
done
