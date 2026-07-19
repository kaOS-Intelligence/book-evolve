/**
 * .env.ai loader — makes the project's model configuration the single source
 * of truth for every CLI command (doctor, smoke, evolve, seed).
 *
 * Values already present in process.env win, so explicit shell exports and
 * CI-injected variables override the file — standard dotenv semantics.
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Load KEY=VALUE pairs from `<projectDir>/.env.ai` into process.env.
 * Returns the keys that were actually applied (unset before, set by file),
 * or null when the file does not exist.
 */
export function loadEnvAi(projectDir: string): string[] | null {
  const file = join(projectDir, '.env.ai');
  if (!existsSync(file)) return null;

  const applied: string[] = [];
  for (const rawLine of readFileSync(file, 'utf-8').split('\n')) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const eq = line.indexOf('=');
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    if (!key || value === '') continue;
    if (process.env[key] === undefined || process.env[key] === '') {
      process.env[key] = value;
      applied.push(key);
    }
  }
  return applied;
}
