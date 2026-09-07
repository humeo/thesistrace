import { createPrivateKey, createPublicKey } from 'node:crypto';
import { fields } from './fields.mjs';
import { fail } from './errors.mjs';

// Deployment policy only. Services still validate their own runtime contracts.
export function validateProduction(values) {
  const check = (name, valid, code) => { if (!valid) fail(code, name); };
  const matches = (name, pattern, code) => check(name, pattern.test(values[name]), code);
  const origin = new URL(values.THESISTRACE_PUBLIC_ORIGIN);
  check('THESISTRACE_PUBLIC_ORIGIN', origin.protocol === 'https:' && !origin.port
    && /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$/i.test(origin.hostname)
    && !/(^|\.)(localhost|test|example|invalid)$/.test(origin.hostname)
    && !/^\d+(\.\d+){3}$/.test(origin.hostname), 'PRODUCTION_PUBLIC_ORIGIN_INVALID');
  for (const [name, code] of [['THESISTRACE_MCP_CLIENT_ID', 'PRODUCTION_MCP_IDENTITY_INVALID'],
  ['THESISTRACE_MCP_AGENT_SCOPES', 'PRODUCTION_MCP_SCOPE_INVALID'],
  ['THESISTRACE_MCP_DEPLOYMENT_TOOLS', 'PRODUCTION_MCP_TOOL_SET_INVALID']]) check(name, values[name] === fields[name].default, code);
  check('THESISTRACE_RESEND_API_URL', values.THESISTRACE_RESEND_API_URL === 'https://api.resend.com', 'PRODUCTION_RESEND_URL_INVALID');
  matches('THESISTRACE_AGENT_OPENAI_BASE_URL', /^https:\/\/[^/@\s?#]+(?:\/[^\s?#]*)?$/, 'PRODUCTION_AGENT_BASE_URL_INVALID');
  for (const name of ['THESISTRACE_S3_ACCESS_KEY_ID', 'THESISTRACE_S3_SECRET_ACCESS_KEY']) check(name,
    /^[A-Za-z0-9_-]{16,128}$/.test(values[name]) && !/test|development|placeholder/.test(values[name]), 'PRODUCTION_STORAGE_CREDENTIAL_INVALID');
  const passwords = ['OWNER', 'CORE', 'AUTH', 'AGENT'].map(role => `THESISTRACE_${role}_DATABASE_PASSWORD`);
  for (const name of passwords) check(name, /^[A-Za-z0-9_-]{24,128}$/.test(values[name]) && !/test-password|development|placeholder/.test(values[name]), 'PRODUCTION_DATABASE_PASSWORD_INVALID');
  if (new Set(passwords.map(name => values[name])).size !== passwords.length) fail('PRODUCTION_DATABASE_PASSWORD_INVALID', ...passwords);
  matches('BETTER_AUTH_SECRET', /^[0-9a-f]{64}$/, 'PRODUCTION_AUTH_SECRET_INVALID');
  matches('RESEND_FROM_EMAIL', /^[^\x00-\x1f]+@[^\x00-\x1f<> ]+>?$/, 'PRODUCTION_RESEND_FROM_INVALID');
  for (const name of ['RESEND_API_KEY', 'THESISTRACE_AGENT_OPENAI_API_KEY', 'THESISTRACE_AGENT_ANTHROPIC_API_KEY', 'THESISTRACE_AGENT_GOOGLE_API_KEY']) {
    if (!values[name]) continue;
    check(name, /^[^\s]{16,512}$/.test(values[name]) && !/^(test-|development-|placeholder|resend-test-key$)/.test(values[name]), name === 'RESEND_API_KEY' ? 'PRODUCTION_RESEND_KEY_INVALID' : 'PRODUCTION_AGENT_PROVIDER_SECRET_INVALID');
  }
  matches('THESISTRACE_AGENT_BUILD_REVISION', /^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$/, 'PRODUCTION_AGENT_BUILD_REVISION_INVALID');
  for (const role of ['AUTH', 'AGENT']) {
    const name = `THESISTRACE_${role}_IMAGE`, value = values[name], code = `PRODUCTION_${role}_IMAGE_INVALID`;
    check(name, /^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$/.test(value)
      || (/^[A-Za-z0-9][A-Za-z0-9._:/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/.test(value)
        && !/^(latest|test|dev|development|placeholder)$/i.test(value.slice(value.lastIndexOf(':') + 1))), code);
  }
  const privateName = 'THESISTRACE_MCP_SIGNING_PRIVATE_JWK', publicName = 'THESISTRACE_MCP_VERIFYING_PUBLIC_JWK';
  let privateJwk, publicJwk;
  try {
    privateJwk = JSON.parse(values[privateName]); publicJwk = JSON.parse(values[publicName]);
    const expected = { alg: 'EdDSA', crv: 'Ed25519', kty: 'OKP', use: 'sig' };
    for (const key of [privateJwk, publicJwk]) {
      if (Object.entries(expected).some(([k, v]) => key[k] !== v) || !/^[A-Za-z0-9_-]{8,128}$/.test(key.kid)
        || /test|development|placeholder/.test(key.kid) || !/^[A-Za-z0-9_-]{43}$/.test(key.x)) throw new Error();
    }
    if (publicJwk.d !== undefined || !/^[A-Za-z0-9_-]{43}$/.test(privateJwk.d) || publicJwk.kid !== privateJwk.kid) throw new Error();
    const derived = createPublicKey(createPrivateKey({ key: privateJwk, format: 'jwk' })).export({ format: 'jwk' });
    if (derived.x !== publicJwk.x || privateJwk.x !== publicJwk.x) throw new Error();
  } catch { fail('PRODUCTION_MCP_SIGNING_KEY_INVALID', privateName, publicName); }
}
