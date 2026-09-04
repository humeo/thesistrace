export type ChatAnswer = Readonly<{ selections: readonly string[]; text: string }>;
export function isChatAnswer(value: unknown): value is ChatAnswer;
export function formatChatAnswer(answer: ChatAnswer): string;
