#!/usr/bin/env node
/**
 * Encrypt or decrypt Nordic Atlas JSON payloads using PBKDF2-SHA256 (210,000 iter)
 * + AES-256-GCM, 100% compatible with browser Web Crypto API (crypto.subtle).
 *
 * Usage:
 *   VAULT_PASSPHRASE="..." node scripts/encrypt_vault.mjs encrypt data/adventures.json data/adventures.enc.json
 *   VAULT_PASSPHRASE="..." node scripts/encrypt_vault.mjs decrypt data/adventures.enc.json data/adventures.json
 */

import crypto from "node:crypto";
import fs from "node:fs";

const ITERATIONS = 210_000;
const KEY_LEN = 32; // 256 bits

function deriveKey(passphrase, salt) {
  return crypto.pbkdf2Sync(passphrase, salt, ITERATIONS, KEY_LEN, "sha256");
}

function encryptFile(inPath, outPath, passphrase) {
  const plaintext = fs.readFileSync(inPath);
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = deriveKey(passphrase, salt);

  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const enc = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const authTag = cipher.getAuthTag();
  // Web Crypto AES-GCM expects ciphertext || 16-byte authTag concatenated
  const combined = Buffer.concat([enc, authTag]);

  const envelope = {
    version: 1,
    kdf: "PBKDF2-SHA256",
    iterations: ITERATIONS,
    cipher: "AES-256-GCM",
    salt: salt.toString("base64"),
    iv: iv.toString("base64"),
    ciphertext: combined.toString("base64"),
  };

  fs.writeFileSync(outPath, JSON.stringify(envelope) + "\n", "utf8");
  return envelope;
}

function decryptEnvelope(envelope, passphrase) {
  const salt = Buffer.from(envelope.salt, "base64");
  const iv = Buffer.from(envelope.iv, "base64");
  const combined = Buffer.from(envelope.ciphertext, "base64");
  const authTag = combined.subarray(combined.length - 16);
  const ciphertext = combined.subarray(0, combined.length - 16);

  const key = crypto.pbkdf2Sync(
    passphrase,
    salt,
    envelope.iterations || ITERATIONS,
    KEY_LEN,
    "sha256"
  );
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(authTag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]);
}

const [, , mode, inPath, outPath] = process.argv;
const passphrase = (process.env.VAULT_PASSPHRASE || "").trim();

if (!passphrase) {
  console.error("Error: Set VAULT_PASSPHRASE environment variable.");
  process.exit(1);
}

if (mode === "encrypt" && inPath && outPath) {
  const env = encryptFile(inPath, outPath, passphrase);
  // Immediately self-verify round-trip decryption!
  const check = decryptEnvelope(env, passphrase);
  JSON.parse(check.toString("utf8"));
  console.log(`Encrypted & verified ${inPath} -> ${outPath} (${(Buffer.byteLength(env.ciphertext) / 1024).toFixed(1)} KB ciphertext)`);
} else if (mode === "decrypt" && inPath && outPath) {
  const env = JSON.parse(fs.readFileSync(inPath, "utf8"));
  const plain = decryptEnvelope(env, passphrase);
  fs.writeFileSync(outPath, plain);
  console.log(`Decrypted ${inPath} -> ${outPath} (${(plain.length / 1024).toFixed(1)} KB)`);
} else {
  console.error("Usage: VAULT_PASSPHRASE=... node scripts/encrypt_vault.mjs [encrypt|decrypt] <in> <out>");
  process.exit(1);
}
