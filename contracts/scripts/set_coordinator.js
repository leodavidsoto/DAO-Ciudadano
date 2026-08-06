const { ethers } = require("hardhat");

async function main() {
  const contractAddress = "0x1CC218883dBeFf6aB8b4933723DF23B8F69336a6";
  const x = "7228337428309680931549016767486512819416118958084767772452626945346249053836";
  const y = "3557376089303270657896465501930508033720789742185631101014209482672995813136";

  const MACI = await ethers.getContractFactory("MACICoordinator");
  const maci = MACI.attach(contractAddress);

  // Check tallyIsVerifiable() first
  const verifiable = await maci.tallyIsVerifiable();
  console.log("tallyIsVerifiable BEFORE:", verifiable);

  console.log("Setting coordinator pub key...");
  const tx = await maci.setCoordinatorPubKey(x, y);
  console.log("Tx hash:", tx.hash);
  await tx.wait();
  console.log("Tx confirmed!");

  const verifiableAfter = await maci.tallyIsVerifiable();
  console.log("tallyIsVerifiable AFTER:", verifiableAfter);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
