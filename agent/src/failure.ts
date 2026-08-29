export class AgentConfigurationError extends Error {
  constructor() {
    super("Agent configuration is invalid");
    this.name = "AgentConfigurationError";
  }
}

export class AgentAuthenticationUnavailableError extends Error {
  constructor() {
    super("Agent authentication is unavailable");
    this.name = "AgentAuthenticationUnavailableError";
  }
}
