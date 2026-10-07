export const MAX_QUESTION_CHARS = 500;

export type QuestionCheck = { ok: true; question: string } | { ok: false; error: string };

/** The same rules the API applies (control characters stripped, whitespace collapsed,
 *  1 to 500 characters), so a bad question is caught before a round trip. */
export function checkQuestion(raw: string): QuestionCheck {
  const cleaned = raw.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "").replace(/\s+/g, " ").trim();
  if (!cleaned) return { ok: false, error: "Type a question first." };
  if (cleaned.length > MAX_QUESTION_CHARS) {
    return { ok: false, error: `Questions can be at most ${MAX_QUESTION_CHARS} characters (this one is ${cleaned.length}).` };
  }
  return { ok: true, question: cleaned };
}

/** Which of the three pipelines have an answer in a (possibly partial, cached) response. */
export function missingPipelines(results: Record<string, unknown>, all: readonly string[]): string[] {
  return all.filter((k) => !results[k]);
}
