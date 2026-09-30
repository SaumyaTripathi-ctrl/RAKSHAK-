// Connects to a Fabric peer through the Gateway API and serves the bridge.
// Defaults match hyperledger/fabric-samples `test-network` (Org1). Override with env vars.
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

import * as grpc from '@grpc/grpc-js';
import { connect, hash, signers } from '@hyperledger/fabric-gateway';

import { createServer } from './server.js';

const env = (k, d) => process.env[k] ?? d;
const cryptoPath = env(
  'FABRIC_CRYPTO_PATH',
  path.resolve(process.cwd(), 'fabric-samples/test-network/organizations/peerOrganizations/org1.example.com'),
);
const channelName = env('FABRIC_CHANNEL', 'mychannel');
const chaincodeName = env('FABRIC_CHAINCODE', 'rakshak');
const mspId = env('FABRIC_MSP_ID', 'Org1MSP');
const peerEndpoint = env('FABRIC_PEER_ENDPOINT', 'localhost:7051');
const peerHostAlias = env('FABRIC_PEER_HOST_ALIAS', 'peer0.org1.example.com');
const port = Number(env('PORT', '8090'));

const tlsCert = await fs.readFile(
  env('FABRIC_TLS_CERT', path.join(cryptoPath, 'peers/peer0.org1.example.com/tls/ca.crt')),
);
const certDir = path.join(cryptoPath, 'users/User1@org1.example.com/msp/signcerts');
const keyDir = path.join(cryptoPath, 'users/User1@org1.example.com/msp/keystore');
const credentials = await fs.readFile(path.join(certDir, (await fs.readdir(certDir))[0]));
const privateKey = crypto.createPrivateKey(await fs.readFile(path.join(keyDir, (await fs.readdir(keyDir))[0])));

const client = new grpc.Client(peerEndpoint, grpc.credentials.createSsl(tlsCert), {
  'grpc.ssl_target_name_override': peerHostAlias,
});
const gateway = connect({
  client,
  identity: { mspId, credentials },
  signer: signers.newPrivateKeySigner(privateKey),
  hash: hash.sha256,
});
const contract = gateway.getNetwork(channelName).getContract(chaincodeName);

createServer(contract, { token: process.env.BRIDGE_TOKEN }).listen(port, () =>
  console.log(`rakshak fabric bridge on :${port} -> ${channelName}/${chaincodeName} via ${peerEndpoint}`),
);
