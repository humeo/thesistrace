export class ConfigurationError extends Error {
  constructor(code, variables = []) { super(code); this.code = code; this.variables = variables; }
}
export function fail(code, ...variables) { throw new ConfigurationError(code, variables); }
export function report(error) {
  process.stderr.write(JSON.stringify({
code: error instanceof ConfigurationError ? error.code : 'CONFIG_INVALID',
    variables: error instanceof ConfigurationError ? error.variables : []
}) + '\n');
  process.exitCode = 2;
}
