const jsonContentType =
  /^\s*application\/json\s*(?:;\s*[!#$%&'*+\-.^_`|~0-9A-Za-z]+\s*=\s*(?:[!#$%&'*+\-.^_`|~0-9A-Za-z]+|"(?:[^"\\\r\n]|\\.)*"))*\s*$/i;

export function isJsonContentType(value: string | null): boolean {
  return value !== null && jsonContentType.test(value);
}
