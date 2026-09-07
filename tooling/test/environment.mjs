import { readFileSync } from 'node:fs';
import { fields } from '../config/fields.mjs';
import { root } from '../config/configuration.mjs';

// Deterministic test credentials and deployment identities. Never load a private .env.
export const fixtureValues = {
  "owner_database_password": "owner-test-password",
  "core_database_password": "core-test-password",
  "auth_database_password": "auth-test-password",
  "agent_database_password": "agent-test-password",
  "resend_api_key": "resend-test-key",
  "resend_from_email": "ThesisTrace <noreply@thesistrace.test>",
  "resend_api_url": "http://resend-fake:8300",
  "tushare_test_token": "0f3d7a91c4e6482b8d5f106a79c2e4b3",
  "agent_scripted_model_secret": "agent-provider-key-private-2529dabd",
  "agent_openai_api_key": "",
  "agent_openai_base_url": "http://provider.invalid/v1",
  "agent_anthropic_api_key": "",
  "agent_google_api_key": "",
  "agent_build_revision": "test-build-revision",
  "agent_run_max_wall_seconds": "600",
  "mcp_access_token_ttl_seconds": "660",
  "mcp_agent_scopes": "[\"research:read\",\"research:execute\",\"tracking:read\",\"tracking:execute\"]",
  "mcp_client_id": "thesistrace-agent",
  "mcp_clock_skew_seconds": "30",
  "mcp_deployment_tools": "[\"diagnose_alpha_formula\",\"get_alpha_catalog\",\"get_daily_track\",\"get_daily_track_result\",\"get_research_batch\",\"get_research_context\",\"get_research_run\",\"get_research_run_result\",\"list_daily_tracks\",\"list_research_batches\",\"list_research_runs\",\"refresh_daily_track\",\"retry_daily_track\",\"start_daily_track\",\"submit_research_batch\",\"submit_research_run\"]",
  "mcp_issuer_url": "",
  "mcp_resource_url": "",
  "mcp_signing_private_jwk": "{\"alg\":\"EdDSA\",\"crv\":\"Ed25519\",\"d\":\"2SCCVM_DYKEJvq18KV1M4UNFhxTHLKtdXxQFXLGlEBs\",\"kid\":\"test-signing-key-01\",\"kty\":\"OKP\",\"use\":\"sig\",\"x\":\"3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8\"}",
  "mcp_verifying_public_jwk": "{\"alg\":\"EdDSA\",\"crv\":\"Ed25519\",\"kid\":\"test-signing-key-01\",\"kty\":\"OKP\",\"use\":\"sig\",\"x\":\"3d8K_V0qubfzURRlfRFt44Yk4LeNW6HkQMaeiPIhJA8\"}"
};
fixtureValues.agent_model_registry = JSON.stringify(JSON.parse(readFileSync(root + '/apps/agent/fixtures/test-model-registry.json', 'utf8')));
const composeNames = {
  "THESISTRACE_TEST_BUCKET": "bucket_name",
  "THESISTRACE_TEST_DATA_MOUNT": "data_mount",
  "THESISTRACE_TEST_BENCHMARK_MOUNT": "benchmark_mount",
  "THESISTRACE_TEST_BATCH_ATTEMPT_CONTROL_DIRECTORY": "batch_attempt_control_directory",
  "THESISTRACE_TEST_RUN_ROOT": "run_root",
  "THESISTRACE_TEST_EVIDENCE_DIR": "evidence_dir",
  "THESISTRACE_TEST_SECRET_DIR": "secret_dir",
  "THESISTRACE_TEST_CADDY_PORT": "caddy_port",
  "THESISTRACE_PUBLIC_ORIGIN": "public_origin",
  "THESISTRACE_OWNER_DATABASE_PASSWORD": "owner_database_password",
  "THESISTRACE_CORE_DATABASE_PASSWORD": "core_database_password",
  "THESISTRACE_AUTH_DATABASE_PASSWORD": "auth_database_password",
  "THESISTRACE_AGENT_DATABASE_PASSWORD": "agent_database_password",
  "THESISTRACE_AGENT_BUILD_REVISION": "agent_build_revision",
  "THESISTRACE_AGENT_MODEL_REGISTRY": "agent_model_registry",
  "THESISTRACE_AGENT_RUN_MAX_WALL_SECONDS": "agent_run_max_wall_seconds",
  "THESISTRACE_AGENT_SCRIPTED_MODEL_SECRET": "agent_scripted_model_secret",
  "THESISTRACE_AGENT_OPENAI_API_KEY": "agent_openai_api_key",
  "THESISTRACE_AGENT_OPENAI_BASE_URL": "agent_openai_base_url",
  "THESISTRACE_AGENT_ANTHROPIC_API_KEY": "agent_anthropic_api_key",
  "THESISTRACE_AGENT_GOOGLE_API_KEY": "agent_google_api_key",
  "THESISTRACE_MCP_ACCESS_TOKEN_TTL_SECONDS": "mcp_access_token_ttl_seconds",
  "THESISTRACE_MCP_AGENT_SCOPES": "mcp_agent_scopes",
  "THESISTRACE_MCP_ALLOWED_HOSTS": "mcp_allowed_hosts",
  "THESISTRACE_MCP_ALLOWED_ORIGINS": "mcp_allowed_origins",
  "THESISTRACE_MCP_CLIENT_ID": "mcp_client_id",
  "THESISTRACE_MCP_CLOCK_SKEW_SECONDS": "mcp_clock_skew_seconds",
  "THESISTRACE_MCP_DEPLOYMENT_TOOLS": "mcp_deployment_tools",
  "THESISTRACE_MCP_ISSUER_URL": "mcp_issuer_url",
  "THESISTRACE_MCP_RESOURCE_URL": "mcp_resource_url",
  "THESISTRACE_MCP_SIGNING_PRIVATE_JWK": "mcp_signing_private_jwk",
  "THESISTRACE_MCP_VERIFYING_PUBLIC_JWK": "mcp_verifying_public_jwk",
  "BETTER_AUTH_SECRET": "auth_secret",
  "RESEND_API_KEY": "resend_api_key",
  "RESEND_FROM_EMAIL": "resend_from_email",
  "THESISTRACE_RESEND_API_URL": "resend_api_url",
  "THESISTRACE_TUSHARE_TOKEN": "tushare_test_token"
};

export function deterministicEnvironment(ambient = process.env) {
  return Object.fromEntries(Object.entries(ambient).filter(([name]) =>
    !/^(THESISTRACE_|COMPOSE_|BETTER_AUTH_|RESEND_|OPENAI_|ANTHROPIC_|GOOGLE_GENERATIVE_AI_|CLI_API_KEY$|CLIPROXY_API_KEY$)/.test(name)));
}

export function composeEnvironment(context) {
  const defaults = Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.default]));
  const selected = Object.fromEntries(Object.entries(composeNames).map(([name, property]) => [name, String(context[property] ?? '')]));
  return { ...context.ambient, ...defaults, ...selected, ...context.eval_controls,
    COMPOSE_ANSI: 'never', COMPOSE_PROGRESS: 'plain', UV_PROJECT: root + '/apps/core',
    THESISTRACE_ENVIRONMENT: 'test', THESISTRACE_S3_ACCESS_KEY_ID: 'rustfsadmin', THESISTRACE_S3_SECRET_ACCESS_KEY: 'rustfsadmin',
    THESISTRACE_AUTH_IMAGE: context.project_name + '-auth', THESISTRACE_AGENT_IMAGE: context.project_name + '-agent',
  };
}

export function hostEnvironment(context) {
  return { ...composeEnvironment(context),
    THESISTRACE_DATABASE_URL: 'postgresql://thesistrace_owner:' + context.owner_database_password + '@127.0.0.1:' + context.postgres_port + '/thesistrace',
    THESISTRACE_AUTH_INTERNAL_ORIGIN: context.auth_internal_origin ?? '',
    THESISTRACE_S3_ENDPOINT_URL: 'http://127.0.0.1:' + context.s3_port,
    THESISTRACE_S3_ACCESS_KEY_ID: context.use_image_overlay ? 'observability-access-canary' : 'rustfsadmin',
    THESISTRACE_S3_SECRET_ACCESS_KEY: context.use_image_overlay ? 'observability-secret-canary' : 'rustfsadmin',
    THESISTRACE_S3_BUCKET: context.bucket_name, THESISTRACE_S3_REGION: 'us-east-1',
    THESISTRACE_DATA_MOUNT: context.data_mount, THESISTRACE_BENCHMARK_MOUNT: context.benchmark_mount,
    THESISTRACE_BATCH_ATTEMPT_CONTROL_DIRECTORY: context.batch_attempt_control_directory,
    THESISTRACE_TEST_PROJECT_NAME: context.project_name, THESISTRACE_TEST_STATE_ROOT: context.state_root,
    THESISTRACE_TEST_PORT_LOCK_ROOT: context.port_lock_root,
    THESISTRACE_TEST_WEB_ORIGIN: context.public_origin,
    THESISTRACE_TEST_RESEND_ORIGIN: context.resend_test_origin ?? '',
    THESISTRACE_TEST_AUTH_FIXTURE_ORIGIN: context.auth_fixture_origin ?? '',
    THESISTRACE_TEST_AUTH_PROXY_ORIGIN: context.auth_proxy_origin ?? '',
    THESISTRACE_TEST_MCP_PROXY_ORIGIN: context.mcp_proxy_origin ?? '',
  };
}
