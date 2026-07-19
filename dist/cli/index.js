#!/usr/bin/env node
/**
 * Book Evolution Tool — CLI Entry Point
 *
 * @kaos-intelligence/book-evolve packages the ASI-Evolve developmental editor pipeline
 * into a single installable CLI. Users run `npx @kaos-intelligence/book-evolve` to
 * scaffold a book project and launch into their chosen AI intelligence.
 */
import { Command } from 'commander';
import { resolve, join } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import chalk from 'chalk';
import { onboard } from './onboard.js';
import { scaffoldProject, detectExistingProject } from './scaffold.js';
import { launchProvider } from './providers.js';
import { runDoctor } from './doctor.js';
import { loadEnvAi } from './envfile.js';
import { startWebUI } from '../web/server.js';
const require = createRequire(import.meta.url);
const { version: PACKAGE_VERSION } = require('../../package.json');
const program = new Command();
/** Prefer the project venv's python; fall back to system python3. */
function projectPython(projectDir) {
    const venv = join(projectDir, '.venv', 'bin', 'python3');
    return existsSync(venv) ? venv : 'python3';
}
/**
 * Load the project's .env.ai so every command sees the same model
 * configuration the evolution run will use. Explicit shell exports win.
 */
function applyProjectEnv(projectDir) {
    const applied = loadEnvAi(projectDir);
    if (applied === null)
        return;
    if (applied.length > 0) {
        console.log(chalk.dim(`  Loaded .env.ai (${applied.length} vars) from ${projectDir}`));
    }
}
/** Light config.yaml reader for book metadata (no YAML dependency needed). */
function readBookMeta(projectDir) {
    const meta = { title: 'Untitled Book', author: 'Author', goal: '' };
    const configPath = join(projectDir, 'config.yaml');
    if (!existsSync(configPath))
        return meta;
    const text = readFileSync(configPath, 'utf-8');
    const grab = (key) => {
        const m = text.match(new RegExp(`^\\s*${key}:\\s*"([^"]*)"`, 'm'));
        return m ? m[1] : null;
    };
    meta.title = grab('title') ?? meta.title;
    meta.author = grab('author') ?? meta.author;
    meta.goal = grab('goal') ?? meta.goal;
    return meta;
}
program
    .name('book-evolve')
    .description('Developmental editor — evolve dictated transcripts into polished book prose')
    .version(PACKAGE_VERSION)
    .option('--web', 'Launch the web-based onboarding wizard at http://localhost:3010')
    .option('--skip-onboard', 'Skip interactive onboarding, use defaults')
    .option('--output <dir>', 'Output directory for the book project', './book-project')
    .action(async (options) => {
    console.log('');
    console.log(chalk.bold.cyan('  BOOK EVOLUTION TOOL'));
    console.log(chalk.dim('  Developmental Editor — 3-Model Evolutionary Council'));
    console.log('');
    const outputDir = resolve(options.output);
    if (options.web) {
        await startWebUI(outputDir);
        return;
    }
    // Check for existing project
    const existing = detectExistingProject(outputDir);
    let config;
    if (existing.exists) {
        // Existing project — skip scaffold, launch into project
        console.log(chalk.green('  Welcome back — existing project found.'));
        console.log(chalk.dim(`  Project: ${outputDir}`));
        console.log('');
        applyProjectEnv(outputDir);
        const meta = readBookMeta(outputDir);
        config = {
            bookTitle: meta.title,
            bookGoal: meta.goal || 'Continue evolving.',
            dictationDir: join(outputDir, 'dictation'),
            referenceDir: join(outputDir, 'author-style'),
            provider: 'terminal',
            outputDir,
            targetScore: 0.93,
            patience: 8,
            maxSteps: 10,
        };
    }
    else {
        // New project
        if (options.skipOnboard) {
            config = {
                bookTitle: 'Untitled Book',
                bookGoal: 'Evolve raw dictated transcripts into polished, publishable prose.',
                dictationDir: join(outputDir, 'dictation'),
                referenceDir: join(outputDir, 'author-style'),
                provider: 'terminal',
                outputDir,
                targetScore: 0.93,
                patience: 8,
                maxSteps: 10,
            };
            console.log(chalk.yellow('  Skipping onboarding — using default configuration.'));
        }
        else {
            config = await onboard(outputDir);
        }
        console.log('');
        console.log(chalk.bold('  Scaffolding project...'));
        const scaffoldPath = await scaffoldProject(config);
        console.log(chalk.green(`  Project created at: ${scaffoldPath}`));
        console.log('');
        console.log(chalk.bold('  Next: verify your environment.'));
        console.log(chalk.dim(`  cd ${options.output} && npx @kaos-intelligence/book-evolve doctor`));
        console.log('');
    }
    await launchProvider(config, outputDir);
});
program
    .command('scaffold')
    .description('Scaffold a new book project or re-scaffold an existing one')
    .option('--title <title>', 'Book title', 'Untitled Book')
    .option('--author <name>', 'Author name (used on the cover and index)')
    .option('--goal <goal>', 'One-sentence goal for the evolution')
    .option('--dir <dir>', 'Project output directory', './book-project')
    .option('-f, --force', 'Re-scaffold even if a project already exists')
    .action(async (options) => {
    const outputDir = resolve(options.dir);
    const config = {
        bookTitle: options.title,
        bookAuthor: options.author,
        bookGoal: options.goal ||
            'Evolve raw dictated transcripts into polished, publishable prose.',
        dictationDir: join(outputDir, 'dictation'),
        referenceDir: join(outputDir, 'author-style'),
        provider: 'terminal',
        outputDir,
        targetScore: 0.93,
        patience: 8,
        maxSteps: 10,
    };
    const path = await scaffoldProject(config, options.force);
    console.log(chalk.green(`Project scaffolded at: ${path}`));
});
program
    .command('setup')
    .description('Create the Python environment and install pipeline dependencies')
    .option('--project <dir>', 'Project directory', '.')
    .action((options) => {
    const projectDir = resolve(options.project);
    const setupScript = join(projectDir, 'setup.sh');
    if (!existsSync(setupScript)) {
        console.error(chalk.red('setup.sh not found — is the pipeline extracted?'));
        console.error(chalk.dim('Run: npx @kaos-intelligence/book-evolve scaffold --dir . --force'));
        process.exitCode = 1;
        return;
    }
    const result = spawnSync('bash', [setupScript], {
        cwd: projectDir,
        stdio: 'inherit',
    });
    if (result.status === 0) {
        // setup.sh prints engine-internal next steps; the supported flow is
        // the CLI, so restate it here where the user is actually standing.
        console.log('');
        console.log(chalk.bold('  Environment ready. Next:'));
        console.log(chalk.dim('  1. cp .env.ai.example .env.ai and set LITELLM_BASE_URL + your models'));
        console.log(chalk.dim('  2. npx @kaos-intelligence/book-evolve doctor'));
        console.log(chalk.dim('  3. npx @kaos-intelligence/book-evolve evolve --chapter 1'));
        console.log('');
    }
    process.exitCode = result.status ?? 1;
});
program
    .command('doctor')
    .description('Verify the project, Python environment, model endpoint, and content are ready')
    .option('--project <dir>', 'Project directory', '.')
    .action(async (options) => {
    const projectDir = resolve(options.project);
    applyProjectEnv(projectDir);
    const ok = await runDoctor(projectDir);
    process.exitCode = ok ? 0 : 1;
});
program
    .command('smoke')
    .description('Live smoke test — one tiny completion per council/judge model plus an embedding round-trip')
    .option('--project <dir>', 'Project directory (its .env.ai is loaded)', '.')
    .action(async (options) => {
    applyProjectEnv(resolve(options.project));
    const { runSmoke } = await import('./doctor.js');
    const ok = await runSmoke();
    process.exitCode = ok ? 0 : 1;
});
program
    .command('seed')
    .description('Seed the cognition store with dictation and reference books')
    .option('--project <dir>', 'Project directory', '.')
    .option('--dictation <file>', 'Path to dictation file')
    .option('--reference <file>', 'Path to reference book file')
    .option('--reference-source <title>', 'Source title for reference')
    .action(async (options) => {
    console.log(chalk.cyan('Seeding cognition store...'));
    applyProjectEnv(resolve(options.project));
    const { seedCognition } = await import('./scaffold.js');
    await seedCognition(resolve(options.project), {
        dictation: options.dictation,
        reference: options.reference,
        referenceSource: options.referenceSource,
    });
});
program
    .command('evolve')
    .description('Run the evolution pipeline (seed → provision → evolve → promote)')
    .option('--project <dir>', 'Project directory', '.')
    .option('--chapter <n>', 'Chapter number to evolve', '1')
    .option('--end-chapter <n>', 'Evolve through this chapter (defaults to --chapter)')
    .option('--target-score <n>', 'Target score cutoff', '0.93')
    .option('--patience <n>', 'No-improvement steps before stopping', '8')
    .option('--max-steps <n>', 'Hard step ceiling', '10')
    .option('--fresh', 'Wipe prior chapter state before evolving')
    .action(async (options) => {
    const projectDir = resolve(options.project);
    applyProjectEnv(projectDir);
    // Preflight the embeddings dependency: the engine requires embeddings
    // (Ollama, or the hash fallback) and fails deep inside Python with a
    // raw traceback otherwise. Catch it here with an actionable message.
    if (!process.env.ASI_EVOLVE_HASH_EMBEDDINGS) {
        const ollamaUrl = process.env.OLLAMA_BASE_URL || 'http://127.0.0.1:11434';
        let ollamaUp = false;
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 4000);
            const res = await fetch(`${ollamaUrl}/api/tags`, {
                signal: controller.signal,
            });
            clearTimeout(timer);
            ollamaUp = res.ok;
        }
        catch {
            ollamaUp = false;
        }
        if (!ollamaUp) {
            console.error(chalk.red(`Embeddings unavailable — Ollama unreachable at ${ollamaUrl}.`));
            console.error(chalk.dim('The evolution engine needs embeddings for retrieval. Either:\n' +
                '  1. Install Ollama (https://ollama.com) and run: ollama pull bge-m3\n' +
                '  2. Or set ASI_EVOLVE_HASH_EMBEDDINGS=1024 to run with degraded keyword-hash retrieval.'));
            process.exitCode = 1;
            return;
        }
    }
    const service = join(projectDir, 'run_book_evolution_service.py');
    if (!existsSync(service)) {
        console.error(chalk.red('Evolution pipeline not found in this project.'));
        console.error(chalk.dim('Run: npx @kaos-intelligence/book-evolve scaffold --dir . --force'));
        process.exitCode = 1;
        return;
    }
    const python = projectPython(projectDir);
    if (python === 'python3') {
        console.log(chalk.yellow('No .venv found — run `book-evolve setup` first for a reliable environment.'));
    }
    const meta = readBookMeta(projectDir);
    const startChapter = options.chapter;
    const endChapter = options.endChapter || options.chapter;
    console.log(chalk.cyan(`Evolving chapters ${startChapter}..${endChapter} of "${meta.title}"...`));
    const args = [
        service,
        '--start-chapter',
        startChapter,
        '--end-chapter',
        endChapter,
        '--max-steps',
        options.maxSteps,
        '--target-score',
        options.targetScore,
        '--patience',
        options.patience,
        '--dictation-dir',
        join(projectDir, 'dictation'),
        '--reference-dir',
        join(projectDir, 'author-style'),
    ];
    if (options.fresh)
        args.push('--fresh');
    const child = spawn(python, args, {
        cwd: projectDir,
        stdio: 'inherit',
        env: {
            ...process.env,
            BOOK_EVOLUTION_TITLE: meta.title,
            BOOK_EVOLUTION_AUTHOR: meta.author,
            BOOK_EVOLUTION_SUBTITLE: meta.goal,
            BOOK_EVOLUTION_OUTPUT_DIR: join(projectDir, 'output'),
        },
    });
    child.on('exit', (code) => {
        if (code === 0) {
            console.log(chalk.green(`Chapters ${startChapter}..${endChapter} evolved successfully.`));
            console.log(chalk.dim(`Output: ${join(projectDir, 'output', 'chapters')}`));
        }
        else {
            console.error(chalk.red(`Evolution failed with exit code ${code}.`));
            console.error(chalk.dim('Run `book-evolve doctor` to check your environment.'));
            process.exitCode = code ?? 1;
        }
    });
});
program.parse(process.argv);
//# sourceMappingURL=index.js.map