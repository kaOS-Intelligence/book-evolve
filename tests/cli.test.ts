/**
 * End-to-end CLI tests — exercise the BUILT CLI (dist/) exactly the way an
 * npx user would: version, scaffold into a temp dir, verify the complete
 * engine lands, re-scaffold guard, doctor behavior, and content safety of
 * the embedded pipeline tarball.
 *
 * Requires `pnpm build` (dist/) and the pipeline tarball (scripts/
 * build-pipeline-tarball.sh) — both are wired into prepublishOnly.
 */
import { execFileSync } from 'node:child_process';
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

const PKG_ROOT = join(__dirname, '..');
const CLI = join(PKG_ROOT, 'dist', 'cli', 'index.js');
const TARBALL = join(PKG_ROOT, 'assets', 'pipeline', 'pipeline.tar.gz');

function runCli(
  args: string[],
  opts: { cwd?: string; allowFailure?: boolean } = {},
): { stdout: string; status: number } {
  try {
    const stdout = execFileSync('node', [CLI, ...args], {
      encoding: 'utf-8',
      cwd: opts.cwd,
      timeout: 60_000,
    });
    return { stdout, status: 0 };
  } catch (err) {
    const e = err as { stdout?: string; status?: number };
    if (!opts.allowFailure) throw err;
    return { stdout: e.stdout ?? '', status: e.status ?? 1 };
  }
}

let projectDir: string;

beforeAll(() => {
  expect(existsSync(CLI), 'dist/cli/index.js must exist — run pnpm build').toBe(
    true,
  );
  expect(
    existsSync(TARBALL),
    'pipeline tarball must exist — run pnpm build:pipeline',
  ).toBe(true);
  projectDir = mkdtempSync(join(tmpdir(), 'book-evolve-test-'));
});

afterAll(() => {
  rmSync(projectDir, { recursive: true, force: true });
});

describe('version', () => {
  it('matches package.json', () => {
    const pkg = JSON.parse(
      readFileSync(join(PKG_ROOT, 'package.json'), 'utf-8'),
    );
    const { stdout } = runCli(['--version']);
    expect(stdout.trim()).toBe(pkg.version);
  });
});

describe('scaffold', () => {
  it('creates a complete standalone project', () => {
    const { stdout } = runCli([
      'scaffold',
      '--title',
      'CLI Test Book',
      '--dir',
      projectDir,
    ]);
    expect(stdout).toContain('Project scaffolded');

    // Engine present at project root
    for (const f of [
      '__init__.py',
      'pipeline/main.py',
      'cognition',
      'database',
      'utils',
      'sacred_guard.py',
      'requirements.txt',
      'setup.sh',
      'run_book_evolution.py',
      'run_book_evolution_service.py',
      'experiments/seed_book_evolution_cognition.py',
      'experiments/book_evolution/config.yaml',
      'experiments/book_evolution/evaluator.py',
      'config.yaml',
      'dictation',
      'author-style',
      'README.md',
    ]) {
      expect(existsSync(join(projectDir, f)), `missing ${f}`).toBe(true);
    }
  });

  it('ships no personal content', () => {
    for (const file of [
      'experiments/book_evolution/dictation/README.md',
      'experiments/book_evolution/author-style/README.md',
    ]) {
      const text = readFileSync(join(projectDir, file), 'utf-8');
      expect(text).not.toContain('Angela');
      expect(text).not.toContain('Blessing of Now');
    }
    // No seeded cognition ships
    expect(
      existsSync(
        join(
          projectDir,
          'experiments/book_evolution/cognition_data/cognition.json',
        ),
      ),
    ).toBe(false);
  });

  it('refuses to overwrite an existing project without --force', () => {
    const { stdout } = runCli([
      'scaffold',
      '--title',
      'Another Book',
      '--dir',
      projectDir,
    ]);
    expect(stdout).toContain('Existing project found');
  });
});

describe('doctor', () => {
  it('reports missing venv and content, exits non-zero', () => {
    const { stdout, status } = runCli(['doctor', '--project', projectDir], {
      allowFailure: true,
    });
    expect(status).toBe(1);
    expect(stdout).toContain('Python environment');
    expect(stdout).toContain('Some checks failed');
  });

  it('detects dictation and reference content once present', () => {
    writeFileSync(join(projectDir, 'dictation', 'ch01.txt'), 'chapter one');
    writeFileSync(join(projectDir, 'author-style', 'sample.txt'), 'style');
    const { stdout } = runCli(['doctor', '--project', projectDir], {
      allowFailure: true,
    });
    expect(stdout).toContain('1 chapter file(s) found');
    expect(stdout).toContain('1 reference file(s) found');
  });
});

describe('pipeline integrity', () => {
  it('every shipped Python file byte-compiles (the v1.1.0 regression)', () => {
    const result = execFileSync(
      'python3',
      ['-m', 'compileall', '-q', projectDir],
      { encoding: 'utf-8' },
    );
    // compileall exits non-zero (throws) on any syntax error; output is
    // empty on success with -q.
    expect(result.trim()).toBe('');
  });

  it('litellm_client contract + env overrides + ${VAR:-default} config', () => {
    const out = execFileSync(
      'python3',
      [join(__dirname, 'pipeline_contract.py'), projectDir],
      { encoding: 'utf-8' },
    );
    expect(out).toContain('CONTRACT-OK');
  });
});

describe('.env.ai loading', () => {
  it('doctor resolves models from the project .env.ai, not built-in defaults', () => {
    const dir = mkdtempSync(join(tmpdir(), 'book-evolve-envai-'));
    try {
      writeFileSync(
        join(dir, '.env.ai'),
        [
          '# comment line',
          'COUNCIL_MODEL_1=envai-model-one',
          'COUNCIL_MODEL_2="envai-model-two"',
          '',
          'JUDGE_MODEL=envai-judge',
        ].join('\n'),
      );
      const { stdout } = runCli(['doctor', '--project', dir], {
        allowFailure: true,
      });
      expect(stdout).toContain('Loaded .env.ai');
      expect(stdout).toContain('envai-model-one');
      // Quoted values are unwrapped
      expect(stdout).toContain('envai-model-two');
      expect(stdout).toContain('envai-judge');
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe('evolve preconditions', () => {
  it('fails cleanly outside a project directory', () => {
    const empty = mkdtempSync(join(tmpdir(), 'book-evolve-empty-'));
    try {
      const { status } = runCli(
        ['evolve', '--project', empty, '--chapter', '1'],
        { allowFailure: true },
      );
      expect(status).toBe(1);
    } finally {
      rmSync(empty, { recursive: true, force: true });
    }
  });
});
