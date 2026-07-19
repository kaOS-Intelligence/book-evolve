/**
 * Provider detection and launch — configures and opens the user's chosen
 * AI intelligence with the book evolution project.
 */
import { execSync } from 'node:child_process';
import { join } from 'node:path';
import chalk from 'chalk';
import ora from 'ora';
export async function launchProvider(config, projectPath) {
    const spinner = ora('Launching into your AI intelligence...').start();
    try {
        switch (config.provider) {
            case 'sovereign':
                await launchSovereign(config, projectPath);
                break;
            case 'cursor':
                await launchCursor(config, projectPath);
                break;
            case 'claude':
                await launchClaude(config, projectPath);
                break;
            case 'terminal':
                await launchTerminal(config, projectPath);
                break;
            case 'api':
                await launchAPI(config, projectPath);
                break;
            default:
                spinner.warn('Unknown provider — outputting terminal instructions.');
                await launchTerminal(config, projectPath);
        }
        spinner.succeed('Ready.');
    }
    catch (err) {
        spinner.fail(`Failed to launch provider: ${err}`);
        console.log('');
        console.log(chalk.yellow('  Fallback: Open the project in your AI of choice and'));
        console.log(chalk.yellow(`  paste the prompt from: ${join(projectPath, 'book-evolve.md')}`));
        console.log('');
    }
    printNextSteps(config, projectPath);
}
async function launchSovereign(config, projectPath) {
    console.log(chalk.cyan('\n  Opening in Sovereign...'));
    console.log(chalk.dim('  If Sovereign is running at :3100, navigate to:'));
    console.log(chalk.bold('  http://localhost:3100/sovereign/evolve'));
    console.log('');
    console.log(chalk.dim('  Or run this command in Cursor:'));
    console.log(chalk.white(`  open "${join(projectPath, 'book-evolve.md')}"`));
}
async function launchCursor(config, projectPath) {
    const rulesDir = join(projectPath, '.cursor', 'rules');
    const rulePath = join(rulesDir, 'book-evolve.mdc');
    console.log(chalk.cyan('\n  Cursor IDE setup ready.'));
    console.log(chalk.dim(`  Rule written: ${rulePath}`));
    console.log('');
    console.log(chalk.dim('  In Cursor, open this project folder and mention'));
    console.log(chalk.dim('  @book-evolve in chat to activate the developmental editor.'));
    console.log('');
    // Try to open Cursor if available
    if (isMacOS()) {
        try {
            execSync(`open -a Cursor "${projectPath}"`, { stdio: 'ignore' });
            console.log(chalk.green('  Opened project in Cursor.'));
        }
        catch {
            console.log(chalk.dim('  Open this project in Cursor manually.'));
        }
    }
}
async function launchClaude(config, projectPath) {
    console.log(chalk.cyan('\n  Claude Desktop setup ready.'));
    console.log(chalk.dim(`  Project config: ${join(projectPath, 'claude-project.json')}`));
    console.log('');
    console.log(chalk.dim('  In Claude Desktop, open the project folder and'));
    console.log(chalk.dim(`  paste the contents of: ${join(projectPath, 'book-evolve.md')}`));
}
async function launchTerminal(config, projectPath) {
    console.log(chalk.cyan('\n  Terminal setup ready.'));
    console.log('');
    console.log(chalk.bold('  Copy this system prompt into your terminal AI:'));
    console.log(chalk.dim('  ─────────────────────────────────────────────'));
    console.log(chalk.white(`  cat "${join(projectPath, 'book-evolve.md')}"`));
    console.log(chalk.dim('  ─────────────────────────────────────────────'));
    console.log('');
    console.log(chalk.dim('  Then start the conversation.'));
}
async function launchAPI(config, projectPath) {
    console.log(chalk.cyan('\n  API endpoint setup ready.'));
    console.log(chalk.dim(`  Environment template: ${join(projectPath, '.env.ai.example')}`));
    console.log('');
    console.log(chalk.bold('  1. Copy .env.ai.example to .env.ai and adjust for your endpoint.'));
    console.log(chalk.bold('  2. Default models (override via COUNCIL_MODEL_1..3, JUDGE_MODEL, FAST_MODEL):'));
    console.log(chalk.dim('     Council: deepseek-v4-pro-cloud, mimo-v2.5-pro-cloud, glm-5.2-cloud'));
    console.log(chalk.dim('     Judge:   deepseek-v4-pro-cloud'));
    console.log(chalk.dim('     Embed:   bge-m3 via Ollama (OLLAMA_EMBED_MODEL)'));
    console.log('');
    console.log(chalk.bold('  3. Verify the model path, then evolve:'));
    console.log(chalk.dim('     npx @kaos-intelligence/book-evolve smoke'));
    console.log(chalk.dim('     npx @kaos-intelligence/book-evolve evolve --project . --chapter 1'));
}
function printNextSteps(config, projectPath) {
    console.log('');
    console.log(chalk.bold.green('  NEXT STEPS'));
    console.log(chalk.dim('  ──────────'));
    console.log('');
    console.log(`${chalk.white('  1. ')}Place your dictation .txt files in:${chalk.dim(` ${config.dictationDir}`)}`);
    console.log(`${chalk.white('  2. ')}Place your reference book .txt files in:${chalk.dim(` ${config.referenceDir}`)}`);
    console.log(`${chalk.white('  3. ')}Seed the cognition store:${chalk.dim(' npx @kaos-intelligence/book-evolve seed --project .')}`);
    console.log(`${chalk.white('  4. ')}Start the conversation by saying:${chalk.bold(' "Begin Chapter One."')}`);
    console.log('');
    console.log(chalk.dim(`  Full prompt: ${join(projectPath, 'book-evolve.md')}`));
    console.log('');
}
function isMacOS() {
    return process.platform === 'darwin';
}
//# sourceMappingURL=providers.js.map