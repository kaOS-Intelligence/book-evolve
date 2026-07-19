/**
 * Doctor — verifies a book-evolve project is fully provisioned and every
 * dependency the evolution pipeline needs is reachable. Run before evolving;
 * every failure includes the exact fix.
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import chalk from 'chalk';

interface CheckResult {
  name: string;
  ok: boolean;
  detail: string;
  fix?: string;
}

// Resolved lazily so .env.ai (loaded by the CLI entry after arg parsing)
// is honored — module-import-time reads would race the file load.
const litellmUrl = () =>
  process.env.LITELLM_BASE_URL || 'http://127.0.0.1:4000/v1';
const ollamaUrl = () => process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434';
const embedModel = () => process.env.OLLAMA_EMBED_MODEL || 'bge-m3:latest';

/**
 * Human-readable one-liner for a fetch failure. Node wraps the useful
 * detail (ECONNREFUSED + host:port) in err.cause; the top-level error is
 * just "TypeError: fetch failed".
 */
function describeError(err: unknown): string {
  const cause = (err as { cause?: { code?: string; message?: string } })?.cause;
  const detail =
    cause?.code || cause?.message
      ? ` (${[cause?.code, cause?.message].filter(Boolean).join(': ')})`
      : '';
  return `${String(err).slice(0, 120)}${detail}`;
}

/**
 * Resolve the API key exactly the way the pipeline does:
 * LITELLM_API_KEY, then ~/.litellm-master-key, then "EMPTY".
 * Returns the key plus a label describing where it came from.
 */
export function resolveApiKey(): { key: string; source: string } {
  const envKey = (process.env.LITELLM_API_KEY || '').trim();
  if (envKey) return { key: envKey, source: 'LITELLM_API_KEY' };
  const keyFile = join(homedir(), '.litellm-master-key');
  if (existsSync(keyFile)) {
    try {
      const key = readFileSync(keyFile, 'utf-8').trim();
      if (key) return { key, source: '~/.litellm-master-key' };
    } catch {
      // unreadable key file — fall through to EMPTY
    }
  }
  return { key: 'EMPTY', source: 'none (unauthenticated)' };
}

function checkPython(): CheckResult {
  const result = spawnSync('python3', ['--version'], { encoding: 'utf-8' });
  if (result.status !== 0) {
    return {
      name: 'Python 3',
      ok: false,
      detail: 'python3 not found on PATH',
      fix: 'Install Python 3.10+ from https://www.python.org/downloads/',
    };
  }
  const version = result.stdout.trim() || result.stderr.trim();
  const match = version.match(/Python (\d+)\.(\d+)/);
  const supported =
    match !== null &&
    (Number(match[1]) > 3 ||
      (Number(match[1]) === 3 && Number(match[2]) >= 10));
  return {
    name: 'Python 3',
    ok: supported,
    detail: version,
    fix: supported ? undefined : 'Python 3.10 or newer is required.',
  };
}

function checkPipeline(projectDir: string): CheckResult {
  const runner = join(projectDir, 'run_book_evolution.py');
  const enginePresent =
    existsSync(runner) &&
    existsSync(join(projectDir, 'pipeline')) &&
    existsSync(join(projectDir, '__init__.py'));
  return {
    name: 'Evolution pipeline',
    ok: enginePresent,
    detail: enginePresent
      ? 'engine extracted'
      : 'pipeline files missing from project directory',
    fix: enginePresent
      ? undefined
      : 'Re-run: npx @kaos-intelligence/book-evolve scaffold --dir . --force',
  };
}

function checkVenv(projectDir: string): CheckResult {
  const venvPython = join(projectDir, '.venv', 'bin', 'python3');
  if (!existsSync(venvPython)) {
    return {
      name: 'Python environment',
      ok: false,
      detail: '.venv not created',
      fix: 'Run: npx @kaos-intelligence/book-evolve setup --project .',
    };
  }
  const result = spawnSync(
    venvPython,
    ['-c', 'import openai, yaml, jinja2, numpy, requests'],
    { encoding: 'utf-8', timeout: 30_000 },
  );
  return {
    name: 'Python environment',
    ok: result.status === 0,
    detail:
      result.status === 0
        ? '.venv ready with all dependencies'
        : `dependencies missing: ${(result.stderr || '').split('\n')[0]}`,
    fix:
      result.status === 0
        ? undefined
        : 'Run: npx @kaos-intelligence/book-evolve setup --project .',
  };
}

async function checkEndpoint(
  name: string,
  url: string,
  fix: string,
): Promise<CheckResult> {
  const { key, source } = resolveApiKey();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { Authorization: `Bearer ${key}` },
    });
    clearTimeout(timer);
    if (res.ok) {
      return {
        name,
        ok: true,
        detail: `reachable + authenticated (${url}, key: ${source})`,
      };
    }
    // 401/403 means the endpoint is up and enforcing auth — reachable, but
    // the pipeline's key chain didn't satisfy it.
    if (res.status === 401 || res.status === 403) {
      return {
        name,
        ok: false,
        detail: `reachable but auth failed (${url}, key source: ${source})`,
        fix: 'Set LITELLM_API_KEY (or write the key to ~/.litellm-master-key).',
      };
    }
    return { name, ok: false, detail: `HTTP ${res.status} from ${url}`, fix };
  } catch {
    return { name, ok: false, detail: `unreachable (${url})`, fix };
  }
}

async function checkOllamaEmbedModel(): Promise<CheckResult> {
  const shortName = embedModel().split(':')[0];
  const name = `Embeddings (${shortName})`;
  const fix = `Install Ollama (https://ollama.com) and run: ollama pull ${shortName}`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(`${ollamaUrl()}/api/tags`, {
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      return { name, ok: false, detail: `Ollama HTTP ${res.status}`, fix };
    }
    const data = (await res.json()) as { models?: { name: string }[] };
    const hasModel = (data.models || []).some(
      (m) => m.name === embedModel() || m.name.startsWith(`${shortName}:`),
    );
    return {
      name,
      ok: hasModel,
      detail: hasModel
        ? `${embedModel()} available via Ollama`
        : `${embedModel()} not pulled`,
      fix: hasModel ? undefined : `Run: ollama pull ${shortName}`,
    };
  } catch {
    return {
      name,
      ok: false,
      detail: `Ollama unreachable (${ollamaUrl()}) — evolve requires embeddings (install Ollama, or set ASI_EVOLVE_HASH_EMBEDDINGS=1024 for degraded retrieval)`,
      fix,
    };
  }
}

function countTxt(dir: string): number {
  if (!existsSync(dir)) return 0;
  return readdirSync(dir).filter((f) => f.endsWith('.txt')).length;
}

function checkContent(projectDir: string): CheckResult[] {
  const dictation = countTxt(join(projectDir, 'dictation'));
  const reference = countTxt(join(projectDir, 'author-style'));
  return [
    {
      name: 'Dictation transcripts',
      ok: dictation > 0,
      detail:
        dictation > 0
          ? `${dictation} chapter file(s) found`
          : 'no .txt files in dictation/',
      fix:
        dictation > 0
          ? undefined
          : 'Drop one .txt file per chapter into dictation/ (chapter order = filename sort order)',
    },
    {
      name: 'Author style references',
      ok: reference > 0,
      detail:
        reference > 0
          ? `${reference} reference file(s) found`
          : 'no .txt files in author-style/ (style matching will be weak)',
      fix:
        reference > 0
          ? undefined
          : 'Drop samples of your published writing into author-style/ — 2-3 chapters of a previous book works well',
    },
  ];
}

/** The council/judge/embedding models the pipeline will actually use. */
export function resolveModels(): {
  council: string[];
  judge: string;
  fast: string;
  embed: string;
} {
  return {
    council: [
      process.env.COUNCIL_MODEL_1 || 'deepseek-v4-pro-cloud',
      process.env.COUNCIL_MODEL_2 || 'mimo-v2.5-pro-cloud',
      process.env.COUNCIL_MODEL_3 || 'glm-5.2-cloud',
    ],
    judge: process.env.JUDGE_MODEL || 'deepseek-v4-pro-cloud',
    fast: process.env.FAST_MODEL || 'deepseek-v4-flash-cloud',
    embed: embedModel(),
  };
}

/**
 * Live smoke test — sends one tiny completion through every unique model the
 * pipeline will use, plus one embedding round-trip. Verifies the entire
 * model path end-to-end in under a minute, before any real evolution run.
 */
export async function runSmoke(): Promise<boolean> {
  console.log('');
  console.log(chalk.bold('  Book Evolution — live smoke test'));
  console.log(chalk.dim(`  Endpoint: ${litellmUrl()}`));
  console.log('');

  const { key, source } = resolveApiKey();
  console.log(chalk.dim(`  API key source: ${source}`));

  const models = resolveModels();
  const chatModels = [
    ...new Set([...models.council, models.judge, models.fast]),
  ];

  let allOk = true;

  for (const model of chatModels) {
    const started = Date.now();
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 60_000);
      const res = await fetch(`${litellmUrl()}/chat/completions`, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${key}`,
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: 'user', content: 'Reply with the single word: ready' },
          ],
          // Reasoning models spend tokens thinking before any visible text;
          // give them room so the reply is observable.
          max_tokens: 2048,
          temperature: 0,
        }),
      });
      clearTimeout(timer);
      const elapsed = ((Date.now() - started) / 1000).toFixed(1);
      if (res.ok) {
        const data = (await res.json()) as {
          choices?: { message?: { content?: string } }[];
        };
        const reply = (data.choices?.[0]?.message?.content || '')
          .trim()
          .slice(0, 40);
        console.log(
          `  ${chalk.green('✓')} ${chalk.bold(model)} — "${reply}" (${elapsed}s)`,
        );
      } else {
        const body = (await res.text()).slice(0, 120);
        console.log(
          `  ${chalk.red('✗')} ${chalk.bold(model)} — HTTP ${res.status}: ${body}`,
        );
        allOk = false;
      }
    } catch (err) {
      console.log(
        `  ${chalk.red('✗')} ${chalk.bold(model)} — ${describeError(err)}\n      ${chalk.dim('Is LITELLM_BASE_URL pointing at a running OpenAI-compatible endpoint with this model routed?')}`,
      );
      allOk = false;
    }
  }

  // Embedding round-trip
  const embedStarted = Date.now();
  const embedLabel = `embeddings (${models.embed})`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30_000);
    const res = await fetch(`${ollamaUrl()}/api/embeddings`, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: models.embed, prompt: 'smoke test' }),
    });
    clearTimeout(timer);
    const elapsed = ((Date.now() - embedStarted) / 1000).toFixed(1);
    if (res.ok) {
      const data = (await res.json()) as { embedding?: number[] };
      const dim = data.embedding?.length || 0;
      const ok = dim > 0;
      console.log(
        `  ${ok ? chalk.green('✓') : chalk.red('✗')} ${chalk.bold(
          embedLabel,
        )} — ${dim}-dim vector (${elapsed}s)`,
      );
      if (!ok) allOk = false;
    } else {
      console.log(
        `  ${chalk.red('✗')} ${chalk.bold(embedLabel)} — HTTP ${res.status}`,
      );
      allOk = false;
    }
  } catch (err) {
    console.log(
      `  ${chalk.red('✗')} ${chalk.bold(embedLabel)} — ${describeError(err)}`,
    );
    allOk = false;
  }

  console.log('');
  if (allOk) {
    console.log(
      chalk.green.bold('  Smoke test passed — the full model path is live.'),
    );
  } else {
    console.log(
      chalk.red.bold('  Smoke test failed.') +
        chalk.dim(' Fix the models/endpoint above before evolving.'),
    );
  }
  console.log('');
  return allOk;
}

export async function runDoctor(projectDir: string): Promise<boolean> {
  console.log('');
  console.log(chalk.bold('  Book Evolution — environment check'));
  console.log(chalk.dim(`  Project: ${projectDir}`));
  console.log('');

  const models = resolveModels();
  console.log(chalk.dim(`  Council: ${models.council.join(', ')}`));
  console.log(
    chalk.dim(
      `  Judge: ${models.judge}   Fast: ${models.fast}   Embeddings: ${models.embed}`,
    ),
  );
  console.log('');

  const results: CheckResult[] = [
    checkPython(),
    checkPipeline(projectDir),
    checkVenv(projectDir),
    await checkEndpoint(
      'Model endpoint',
      `${litellmUrl()}/models`,
      'Point LITELLM_BASE_URL at any OpenAI-compatible endpoint with your council models routed (LiteLLM proxy, vLLM, OpenRouter, ...).',
    ),
    await checkOllamaEmbedModel(),
    ...checkContent(projectDir),
  ];

  let allRequired = true;
  for (const r of results) {
    const icon = r.ok ? chalk.green('✓') : chalk.red('✗');
    console.log(`  ${icon} ${chalk.bold(r.name)} — ${r.detail}`);
    if (!r.ok && r.fix) {
      console.log(chalk.yellow(`      fix: ${r.fix}`));
    }
    // Style references are a soft warning, everything else is required.
    if (!r.ok && r.name !== 'Author style references') {
      allRequired = false;
    }
  }

  console.log('');
  if (allRequired) {
    console.log(chalk.green.bold('  All checks passed. Ready to evolve.'));
    console.log(
      chalk.dim(
        '  Run: npx @kaos-intelligence/book-evolve evolve --project . --chapter 1',
      ),
    );
  } else {
    console.log(
      chalk.red.bold('  Some checks failed.') +
        chalk.dim(' Apply the fixes above and re-run doctor.'),
    );
  }
  console.log('');
  return allRequired;
}
