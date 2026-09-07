export class AuthBackgroundTasks {
  readonly #pending = new Set<Promise<unknown>>();
  readonly #onError: (error: unknown) => void;

  constructor(onError: (error: unknown) => void = () => undefined) {
    this.#onError = onError;
  }

  readonly handler = (promise: Promise<unknown>): void => {
    const tracked = Promise.resolve(promise)
      .catch((error: unknown) => {
        this.#onError(error);
      })
      .finally(() => {
        this.#pending.delete(tracked);
      });
    this.#pending.add(tracked);
  };

  async drain(): Promise<void> {
    while (this.#pending.size !== 0) {
      await Promise.allSettled([...this.#pending]);
    }
  }
}
