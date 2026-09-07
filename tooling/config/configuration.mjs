import { generateKeyPairSync, randomBytes, randomUUID } from 'node:crypto';
import { lstatSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { isAbsolute, relative, resolve, sep } from 'node:path';
import { parseEnv } from 'node:util';
import { fields } from './fields.mjs';
import { fail } from './errors.mjs';
export { fail, report } from './errors.mjs';
import { validateProduction } from './production.mjs';

export const root = resolve(import.meta.dirname, '../..');
export function configurationFile(mode = 'development', env = process.env) {
  const chosen = env.THESISTRACE_ENV_FILE;
  if (mode === 'production' && (!chosen || !isAbsolute(chosen))) fail('PRODUCTION_ENV_FILE_PATH_INVALID');
  return resolve(chosen ?? resolve(root, '.env'));
}
export function readConfiguration(file, mode = 'development') {
  let metadata;
  try { metadata = lstatSync(file); } catch { fail('CONFIG_FILE_MISSING_RUN_CONFIG_INIT'); }
  if (!metadata.isFile() || metadata.isSymbolicLink()) fail('CONFIG_FILE_PERMISSIONS_INVALID');
  if ((metadata.mode & 0o777) !== 0o600 || (mode === 'production' && metadata.uid !== 0)) {
    fail(mode === 'production' ? 'PRODUCTION_ENV_FILE_PERMISSIONS_INVALID' : 'CONFIG_FILE_PERMISSIONS_INVALID');
  }
  if (mode === 'production') {
    const path = relative(realpathSync(root), realpathSync(file));
    if (!path.startsWith(`..${sep}`) && !isAbsolute(path)) fail('PRODUCTION_ENV_FILE_PATH_INVALID');
  }
  let source;
  try { source = readFileSync(file, 'utf8'); } catch { fail('CONFIG_FILE_READ_FAILED'); }
  const seen = new Set();
  for (const line of source.split('\n')) {
    if (!line.trim() || line.trimStart().startsWith('#')) continue;
    const match = /^([A-Z][A-Z0-9_]*)=(.*)$/.exec(line);
    if (!match) fail('CONFIG_FILE_SYNTAX_INVALID');
    const [, name, value] = match;
    if (!Object.hasOwn(fields, name)) fail('CONFIG_VARIABLE_UNKNOWN', name);
    if (seen.has(name)) fail('CONFIG_VARIABLE_DUPLICATED', name);
    seen.add(name);
    if (value !== value.trim() || /^["']/.test(value) || /[\r$#\x00]/.test(value)) fail('CONFIG_LITERAL_REQUIRED', name);
  }
  return { ...Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.default])), ...parseEnv(source) };
}
function validateFields(values, mode) {
  if (values.THESISTRACE_ENVIRONMENT !== mode) fail('CONFIG_ENVIRONMENT_INVALID', 'THESISTRACE_ENVIRONMENT');
  for (const [name, field] of Object.entries(fields)) {
    const value = values[name];
    if (!value && (field.required === true || field.required === mode)) fail('CONFIG_VALUE_MISSING', name);
    if (!value) continue;
    if (field.type === 'integer' && (!/^(0|[1-9][0-9]*)$/.test(value) || !Number.isSafeInteger(Number(value)))) fail('CONFIG_INTEGER_INVALID', name);
    if (field.type === 'string-array') {
      let parsed; try { parsed = JSON.parse(value); } catch { fail('CONFIG_ARRAY_INVALID', name); }
      if (!Array.isArray(parsed) || !parsed.length || parsed.some(item => typeof item !== 'string' || !item) || new Set(parsed).size !== parsed.length) fail('CONFIG_ARRAY_INVALID', name);
    }
    if (name.endsWith('_PORT') && (Number(value) < 1 || Number(value) > 65535)) fail('CONFIG_PORT_INVALID', name);
  }
  const token = values.THESISTRACE_TUSHARE_TOKEN;
  if (token.length < 8 || token.length > 512 || /\s/.test(token) || /^(test-|development-|placeholder|changeme$|dummy$|example$|tushare-test-token$|<.*>$)/i.test(token)) fail('CONFIG_CREDENTIAL_INVALID', 'THESISTRACE_TUSHARE_TOKEN');
  for (const role of ['RESEARCH', 'BATCH_RESEARCH', 'TRACKING']) {
    const prefix = `THESISTRACE_${role}_WORKER_`;
    const cpu = Number(values[prefix + 'CPU_COUNT']); const mem = Number(values[prefix + 'MEMORY_BYTES']);
    const threads = Number(values[prefix + 'CALCULATION_THREADS']); const execution = Number(values[prefix + 'EXECUTION_MEMORY_BYTES']);
    if (cpu < 1 || mem < 1 || threads < 1 || threads > cpu || execution < 1 || execution > Math.floor(mem * 3 / 4)) fail('CONFIG_WORKER_CAPACITY_INVALID', prefix + 'CPU_COUNT', prefix + 'MEMORY_BYTES', prefix + 'EXECUTION_MEMORY_BYTES', prefix + 'CALCULATION_THREADS');
  }
  const wall = Number(values.THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS), skew = Number(values.THESISTRACE_MCP_CLOCK_SKEW_SECONDS), ttl = Number(values.THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS);
  if (wall < 1 || wall > 3600 || skew > 300 || ttl > 86400 || ttl <= wall + skew) fail('CONFIG_MCP_TIME_BUDGET_INVALID', 'THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS', 'THESISTRACE_MCP_CLOCK_SKEW_SECONDS', 'THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS');
}
function publicIdentity(values, mode) {
  const name = 'THESISTRACE_PUBLIC_ORIGIN';
  let url;
  try { url = new URL(values[name]); } catch { fail('CONFIG_PUBLIC_ORIGIN_INVALID', name); }
  if (url.origin !== values[name] || !['http:', 'https:'].includes(url.protocol)
    || (mode === 'development' && (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname)))) {
    fail('CONFIG_PUBLIC_ORIGIN_INVALID', name);
  }
  return {
    THESISTRACE_DEV_WEB_PORT: url.port || (url.protocol === 'https:' ? '443' : '80'),
    THESISTRACE_MCP_ISSUER_URL: `${url.origin}/api/auth`,
    THESISTRACE_MCP_RESOURCE_URL: `${url.origin}/mcp`,
    THESISTRACE_MCP_ALLOWED_HOSTS: JSON.stringify(['api:8100', url.host]),
    THESISTRACE_MCP_ALLOWED_ORIGINS: JSON.stringify([url.origin]),
  };
}
function modelRegistry(values) {
  let registry;
  try {
    const source = readFileSync(resolve(root, 'config/model-registry.json'), 'utf8');
    if (Buffer.byteLength(source, 'utf8') > 65_536) fail('CONFIG_MODEL_REGISTRY_INVALID');
    registry = JSON.parse(source);
  } catch { fail('CONFIG_MODEL_REGISTRY_INVALID'); }
  const providers = { openai: 'THESISTRACE_AGENT_OPENAI_API_KEY', anthropic: 'THESISTRACE_AGENT_ANTHROPIC_API_KEY', google: 'THESISTRACE_AGENT_GOOGLE_API_KEY' };
  if (!Array.isArray(registry.models) || !registry.models.some(m => m.enabled && m.key === registry.default_model_key)) fail('CONFIG_MODEL_REGISTRY_INVALID');
  for (const model of registry.models) {
    if (providers[model.provider_adapter] !== model.secret_env) fail('CONFIG_MODEL_REGISTRY_INVALID');
    if (model.enabled && !values[model.secret_env]) fail('CONFIG_VALUE_MISSING', model.secret_env);
  }
  return JSON.stringify(registry);
}
export function loadConfiguration({ file = configurationFile(), mode = 'development', ambient = process.env } = {}) {
  const values = readConfiguration(file, mode);
  validateFields(values, mode);
  const identity = publicIdentity(values, mode);
  const registry = modelRegistry(values);
  if (mode === 'production') validateProduction(values);
  const environment = { ...ambient };
  // Service-local and Compose controls must not replace selected deployment inputs.
  for (const name of Object.keys(environment)) if (/^(THESISTRACE_|COMPOSE_|BETTER_AUTH_|RESEND_|OPENAI_BASE_URL$)/.test(name)) delete environment[name];
  return { ...environment, ...values, ...identity, THESISTRACE_AGENT_MODEL_REGISTRY: registry };
}
export function template(generated = {}) {
  let section = '';
  const lines = ['# Generated from tooling/config/fields.mjs. Run pnpm config:init to create a private .env.',
    '# Single-line literals only: no $, #, outer quotes or inline comments.',
    '# THESISTRACE_ENV_FILE selects the authoritative file. Ambient deployment values are ignored.', ''];
  for (const [name, field] of Object.entries(fields)) {
    if (section !== field.section) { lines.push('', `# ${field.section}`); section = field.section; }
    lines.push(`${name}=${generated[name] ?? field.default}`);
  }
  return lines.join('\n') + '\n';
}
export function initialize(file) {
  const generated = {};
  for (const name of Object.keys(fields)) if (/PASSWORD$|^BETTER_AUTH_SECRET$|^THESISTRACE_S3_SECRET_ACCESS_KEY$/.test(name)) generated[name] = randomBytes(32).toString('hex');
  generated.THESISTRACE_S3_ACCESS_KEY_ID = randomBytes(16).toString('hex');
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const privateJwk = privateKey.export({ format: 'jwk' }), publicJwk = publicKey.export({ format: 'jwk' }), kid = `development-${randomUUID()}`;
  generated.THESISTRACE_MCP_SIGNING_PRIVATE_JWK = JSON.stringify({ alg: 'EdDSA', crv: privateJwk.crv, d: privateJwk.d, kid, kty: privateJwk.kty, use: 'sig', x: privateJwk.x });
  generated.THESISTRACE_MCP_VERIFYING_PUBLIC_JWK = JSON.stringify({ alg: 'EdDSA', crv: publicJwk.crv, kid, kty: publicJwk.kty, use: 'sig', x: publicJwk.x });
  try { writeFileSync(file, template(generated), { flag: 'wx', mode: 0o600 }); }
  catch (error) { fail(error.code === 'EEXIST' ? 'CONFIG_FILE_ALREADY_EXISTS' : 'CONFIG_FILE_WRITE_FAILED'); }
}
