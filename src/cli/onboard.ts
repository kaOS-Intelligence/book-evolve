/**
 * Interactive onboarding wizard.
 *
 * Guides the user through setting up their book evolution project:
 * book goal, dictation files, reference books, AI provider selection.
 */
import inquirer from 'inquirer';
import chalk from 'chalk';
import ora from 'ora';
import { existsSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ProjectConfig, ProviderType } from './types.js';

export async function onboard(defaultOutput: string): Promise<ProjectConfig> {
  console.log(chalk.bold("  Let's set up your book project."));
  console.log(
    chalk.dim("  I'll ask a few questions, then scaffold everything for you."),
  );
  console.log('');

  const { bookTitle } = await inquirer.prompt<{ bookTitle: string }>([
    {
      type: 'input',
      name: 'bookTitle',
      message: 'Working title for your book:',
      default: 'Untitled Book',
      validate: (input: string) =>
        input.trim().length > 0 ? true : 'Please enter a title.',
    },
  ]);

  const { bookGoal } = await inquirer.prompt<{ bookGoal: string }>([
    {
      type: 'input',
      name: 'bookGoal',
      message: 'One-sentence goal or description:',
      default:
        'Evolve raw dictated transcripts into polished, publishable prose.',
    },
  ]);

  const { useDefaults } = await inquirer.prompt<{ useDefaults: boolean }>([
    {
      type: 'confirm',
      name: 'useDefaults',
      message: 'Use project directory structure defaults?',
      default: true,
    },
  ]);

  let dictationDir: string;
  let referenceDir: string;

  if (useDefaults) {
    dictationDir = resolve(defaultOutput, 'dictation');
    referenceDir = resolve(defaultOutput, 'author-style');
    console.log(chalk.dim(`  Dictation: ${dictationDir}`));
    console.log(chalk.dim(`  Reference:  ${referenceDir}`));
  } else {
    const { customDictation } = await inquirer.prompt<{
      customDictation: string;
    }>([
      {
        type: 'input',
        name: 'customDictation',
        message: 'Path to your dictation files directory:',
        default: resolve(defaultOutput, 'dictation'),
      },
    ]);
    dictationDir = customDictation;

    const { customReference } = await inquirer.prompt<{
      customReference: string;
    }>([
      {
        type: 'input',
        name: 'customReference',
        message: 'Path to your reference book files directory:',
        default: resolve(defaultOutput, 'author-style'),
      },
    ]);
    referenceDir = customReference;
  }

  const { provider } = await inquirer.prompt<{ provider: ProviderType }>([
    {
      type: 'list',
      name: 'provider',
      message: 'Which AI intelligence will you use for the editorial work?',
      choices: [
        {
          name: 'Cursor IDE — your configured models in your editor',
          value: 'cursor',
        },
        { name: "Claude Desktop — Anthropic's desktop app", value: 'claude' },
        {
          name: 'Terminal — any CLI-based AI with an API key',
          value: 'terminal',
        },
        {
          name: 'API — bring your own OpenAI-compatible endpoint',
          value: 'api',
        },
      ],
    },
  ]);

  // Detect existing files
  const dictationFiles = scanDir(dictationDir);
  const referenceFiles = scanDir(referenceDir);

  if (dictationFiles.length > 0) {
    console.log(
      chalk.dim(
        `  Found ${dictationFiles.length} dictation file(s): ${dictationFiles.join(', ')}`,
      ),
    );
  } else {
    console.log(
      chalk.yellow(
        `  No dictation files found in ${dictationDir}. Drop your .txt files there.`,
      ),
    );
  }

  if (referenceFiles.length > 0) {
    console.log(
      chalk.dim(
        `  Found ${referenceFiles.length} reference file(s): ${referenceFiles.join(', ')}`,
      ),
    );
  } else {
    console.log(
      chalk.yellow(
        `  No reference files found in ${referenceDir}. Drop your .txt files there.`,
      ),
    );
  }

  return {
    bookTitle: bookTitle.trim(),
    bookGoal: bookGoal.trim(),
    dictationDir,
    referenceDir,
    provider,
    outputDir: resolve(defaultOutput),
    targetScore: 0.93,
    patience: 8,
    maxSteps: 10,
  };
}

function scanDir(dirPath: string): string[] {
  if (!existsSync(dirPath)) return [];
  return readdirSync(dirPath)
    .filter((f) => f.endsWith('.txt') || f.endsWith('.md'))
    .slice(0, 10);
}
