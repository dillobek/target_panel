import { createCipheriv, randomBytes } from 'crypto';

// Format: base64(iv[12] | ciphertext | tag[16]) — Python AESGCM bilan mos
function key(): Buffer {
  const k = Buffer.from(process.env.ENCRYPTION_KEY ?? '', 'base64');
  if (k.length !== 32) throw new Error("ENCRYPTION_KEY 32 baytli base64 bo'lishi kerak");
  return k;
}

export function encrypt(plain: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key(), iv);
  const enc = Buffer.concat([cipher.update(plain, 'utf8'), cipher.final()]);
  return Buffer.concat([iv, enc, cipher.getAuthTag()]).toString('base64');
}
