import { AsyncLocalStorage } from "node:async_hooks";

export class InvitationAdmission {
  readonly #email = new AsyncLocalStorage<string>();

  allows(email: string): boolean {
    return this.#email.getStore() === email;
  }

  isActive(): boolean {
    return this.#email.getStore() !== undefined;
  }

  run<T>(email: string, operation: () => Promise<T>): Promise<T> {
    return this.#email.run(email, operation);
  }
}
