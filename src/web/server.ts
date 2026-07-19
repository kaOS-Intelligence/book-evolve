/**
 * Web-based onboarding UI.
 *
 * Starts a simple HTTP server at http://localhost:3010
 * with a visual onboarding wizard. Scaffolds the project
 * on form submission, then shuts down.
 */
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';
import { join } from 'node:path';
import chalk from 'chalk';
import { exec } from 'node:child_process';
import { scaffoldProject, detectExistingProject } from '../cli/scaffold.js';
import type { ProjectConfig, ProviderType } from '../cli/types.js';

const PORT = 3010;

export async function startWebUI(outputDir: string): Promise<void> {
  // eslint-disable-next-line prefer-const — referenced inside its own handler
  const server = createServer(
    async (req: IncomingMessage, res: ServerResponse) => {
      if (req.url === '/' || req.url === '/index.html') {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        res.end(getOnboardingHTML(outputDir));
      } else if (req.url === '/api/detect' && req.method === 'GET') {
        // Let the frontend know if a project already exists
        const existing = detectExistingProject(outputDir);
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ exists: existing.exists, path: outputDir }));
      } else if (req.url === '/api/config' && req.method === 'POST') {
        let body = '';
        req.on('data', (chunk: Buffer) => {
          body += chunk.toString();
        });
        req.on('end', async () => {
          try {
            const raw = JSON.parse(body);
            const config: ProjectConfig = {
              bookTitle: (raw.bookTitle || 'Untitled Book').trim(),
              bookGoal: (
                raw.bookGoal || 'Evolve raw dictation into polished prose.'
              ).trim(),
              dictationDir: raw.dictationDir || join(outputDir, 'dictation'),
              referenceDir: raw.referenceDir || join(outputDir, 'author-style'),
              provider: (raw.provider || 'terminal') as ProviderType,
              outputDir: raw.outputDir || outputDir,
              targetScore: 0.93,
              patience: 8,
              maxSteps: 10,
            };

            const scaffoldPath = await scaffoldProject(
              config,
              raw.force === true,
            );

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ ok: true, path: scaffoldPath }));

            console.log('');
            console.log(chalk.green(`  Project at: ${scaffoldPath}`));
            console.log(
              chalk.dim(
                '  Wizard still running — scaffold more projects, or press "Done" (or Ctrl-C) to exit.',
              ),
            );
          } catch (err) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ ok: false, error: String(err) }));
          }
        });
      } else if (req.url === '/api/shutdown' && req.method === 'POST') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
        setTimeout(() => {
          console.log(chalk.dim('  Web UI shut down.'));
          server.close();
          process.exit(0);
        }, 300);
      } else {
        res.writeHead(404);
        res.end('Not found');
      }
    },
  );

  return new Promise((resolve) => {
    server.listen(PORT, () => {
      console.log('');
      console.log(
        chalk.bold.green(
          `  Book Evolution Onboarding running at http://localhost:${PORT}`,
        ),
      );
      console.log(
        chalk.dim('  Fill in the form to scaffold your book project.'),
      );
      console.log('');

      // Try to open browser
      const platform = process.platform;
      const url = `http://localhost:${PORT}`;
      if (platform === 'darwin') {
        exec(`open "${url}"`);
      } else if (platform === 'win32') {
        exec(`start "" "${url}"`);
      } else {
        exec(`xdg-open "${url}"`);
      }

      resolve();
    });
  });
}

function getOnboardingHTML(outputDir: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Book Evolution — Onboarding</title>
  <style>
    :root {
      --bg: #0a0a0f;
      --surface: #14141f;
      --border: #2a2a3a;
      --text: #e4e4ec;
      --text-dim: #8888a0;
      --accent: #c4a35a;
      --accent-dim: #7a6538;
      --green: #4ade80;
      --red: #f87171;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
    }
    .container {
      max-width: 720px;
      width: 100%;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 3rem;
    }
    h1 {
      font-size: 1.75rem;
      font-weight: 600;
      color: var(--accent);
      margin-bottom: 0.5rem;
      letter-spacing: -0.02em;
    }
    .subtitle {
      color: var(--text-dim);
      margin-bottom: 2rem;
      font-size: 0.95rem;
      line-height: 1.5;
    }
    .field {
      margin-bottom: 1.5rem;
    }
    label {
      display: block;
      font-size: 0.85rem;
      font-weight: 500;
      margin-bottom: 0.5rem;
      color: var(--text-dim);
    }
    input, select, textarea {
      width: 100%;
      padding: 0.75rem 1rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--text);
      font-size: 0.95rem;
      font-family: inherit;
      transition: border-color 0.2s;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
    }
    textarea { min-height: 80px; resize: vertical; }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.75rem 1.5rem;
      background: var(--accent);
      color: #0a0a0f;
      border: none;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    .btn:hover { opacity: 0.9; }
    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    .btn-secondary {
      background: transparent;
      border: 1px solid var(--border);
      color: var(--text);
    }
    .btn-row {
      display: flex;
      gap: 0.75rem;
      margin-top: 1rem;
    }
    .result {
      margin-top: 2rem;
      padding: 1.5rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      display: none;
    }
    .result.active { display: block; }
    .result h2 {
      font-size: 1rem;
      color: var(--green);
      margin-bottom: 0.5rem;
    }
    .result p {
      color: var(--text-dim);
      font-size: 0.9rem;
      line-height: 1.5;
    }
    .result .path {
      margin-top: 0.75rem;
      padding: 0.75rem 1rem;
      background: #000;
      border-radius: 6px;
      font-family: monospace;
      font-size: 0.85rem;
      color: var(--green);
      word-break: break-all;
    }
    .error {
      margin-top: 1rem;
      padding: 1rem;
      background: rgba(248, 113, 113, 0.1);
      border: 1px solid var(--red);
      border-radius: 8px;
      color: var(--red);
      font-size: 0.9rem;
      display: none;
    }
    .error.active { display: block; }
    .spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid transparent;
      border-top-color: #0a0a0f;
      border-radius: 50%;
      animation: spin 0.6s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .welcome-back {
      display: none;
      text-align: center;
      padding: 1rem 0;
    }
    .welcome-back.active { display: block; }
    .welcome-back .icon {
      font-size: 2.5rem;
      margin-bottom: 1rem;
    }
    .welcome-back p {
      color: var(--text-dim);
      font-size: 0.95rem;
      line-height: 1.6;
    }
    .welcome-back .project-path {
      margin: 1rem 0;
      padding: 0.75rem 1rem;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      font-family: monospace;
      font-size: 0.85rem;
      color: var(--accent);
      word-break: break-all;
    }
  </style>
</head>
<body>
  <div class="container">
    <h1>Book Evolution</h1>
    <p class="subtitle" id="subtitle">
      Developmental editor powered by a 3-model evolutionary council.
      Fill in the details below to scaffold your book project.
    </p>

    <!-- Existing project state -->
    <div id="welcome-back" class="welcome-back">
      <div class="icon">&#x1F4D6;</div>
      <p>An existing book project was found at:</p>
      <div class="project-path" id="existing-path"></div>
      <p>Would you like to continue working on it, or start fresh?</p>
      <div class="btn-row" style="justify-content: center;">
        <button class="btn" id="continue-btn">Continue</button>
        <button class="btn btn-secondary" id="fresh-btn">Start Fresh</button>
      </div>
    </div>

    <!-- New project form -->
    <form id="onboard-form" style="display: none;">
      <div class="field">
        <label for="title">Working Book Title</label>
        <input type="text" id="title" name="title" placeholder="My Book" required>
      </div>

      <div class="field">
        <label for="goal">One-sentence Goal</label>
        <input type="text" id="goal" name="goal" placeholder="Evolve raw dictation into polished prose." required>
      </div>

      <div class="field">
        <label for="dictation">Dictation Files Directory</label>
        <input type="text" id="dictation" name="dictation" placeholder="${outputDir}/dictation">
      </div>

      <div class="field">
        <label for="reference">Reference Books Directory</label>
        <input type="text" id="reference" name="reference" placeholder="${outputDir}/author-style">
      </div>

      <div class="field">
        <label for="provider">AI Intelligence</label>
        <select id="provider" name="provider">
          <option value="cursor">Cursor IDE</option>
          <option value="claude">Claude Desktop</option>
          <option value="terminal">Terminal / API key</option>
          <option value="api">API — bring your own endpoint</option>
        </select>
      </div>

      <button type="submit" class="btn" id="submit-btn">Scaffold Project</button>
    </form>

    <div id="error" class="error"></div>

    <div id="result" class="result">
      <h2>Project Ready</h2>
      <p id="result-msg">Your book project has been scaffolded and is ready.</p>
      <div class="path" id="result-path"></div>
      <p style="margin-top: 1rem;">
        Open the project in your AI editor of choice and start with
        <strong>"Begin Chapter One."</strong>
      </p>
      <div class="btn-row">
        <button class="btn btn-secondary" id="another-btn">Scaffold Another</button>
        <button class="btn" id="done-btn">Done</button>
      </div>
    </div>
  </div>

  <script>
    const outputDir = '${outputDir}';
    const form = document.getElementById('onboard-form');
    const welcomeBack = document.getElementById('welcome-back');
    const subtitle = document.getElementById('subtitle');

    // Check for existing project on load
    (async () => {
      try {
        const resp = await fetch('/api/detect');
        const data = await resp.json();
        if (data.exists) {
          document.getElementById('existing-path').textContent = data.path;
          welcomeBack.classList.add('active');
          form.style.display = 'none';
          subtitle.textContent = 'Existing project detected.';
        } else {
          form.style.display = 'block';
        }
      } catch {
        form.style.display = 'block';
      }
    })();

    // Result-panel buttons — re-enter the form, or shut the wizard down
    document.getElementById('another-btn').addEventListener('click', () => {
      document.getElementById('result').classList.remove('active');
      form.reset();
      delete form.dataset.force;
      form.style.display = 'block';
      const btn = document.getElementById('submit-btn');
      btn.disabled = false;
      btn.textContent = 'Scaffold Project';
      subtitle.textContent = 'Start a new book project.';
    });
    document.getElementById('done-btn').addEventListener('click', async () => {
      try { await fetch('/api/shutdown', { method: 'POST' }); } catch {}
      document.body.innerHTML = '<div class="container"><h1>Book Evolution</h1><p class="subtitle">Wizard closed. You can close this tab.</p></div>';
    });

    // Continue button — just close the server
    document.getElementById('continue-btn').addEventListener('click', async () => {
      const btn = document.getElementById('continue-btn');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Loading...';
      try {
        await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'terminal' }),
        });
      } catch {}
      document.getElementById('result-msg').textContent = 'Continuing with existing project.';
      document.getElementById('result-path').textContent = outputDir;
      document.getElementById('result').classList.add('active');
    });

    // Start Fresh button — show form with force
    document.getElementById('fresh-btn').addEventListener('click', () => {
      welcomeBack.classList.remove('active');
      form.style.display = 'block';
      subtitle.textContent = 'Start a new book project.';
      // Mark form for force mode
      form.dataset.force = 'true';
    });

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('submit-btn');
      const errorEl = document.getElementById('error');
      const resultEl = document.getElementById('result');

      errorEl.classList.remove('active');
      resultEl.classList.remove('active');
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Scaffolding...';

      const config = {
        bookTitle: form.title.value,
        bookGoal: form.goal.value,
        dictationDir: form.dictation.value || undefined,
        referenceDir: form.reference.value || undefined,
        provider: form.provider.value,
        force: form.dataset.force === 'true',
      };

      try {
        const resp = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        const data = await resp.json();

        if (data.ok) {
          document.getElementById('result-msg').textContent = 'Your book project has been scaffolded and is ready.';
          document.getElementById('result-path').textContent = data.path;
          resultEl.classList.add('active');
          resultEl.scrollIntoView({ behavior: 'smooth' });
          btn.textContent = 'Done';
        } else {
          errorEl.textContent = 'Error: ' + (data.error || 'Unknown error');
          errorEl.classList.add('active');
          btn.disabled = false;
          btn.textContent = 'Scaffold Project';
        }
      } catch (err) {
        errorEl.textContent = 'Network error: ' + err.message;
        errorEl.classList.add('active');
        btn.disabled = false;
        btn.textContent = 'Scaffold Project';
      }
    });
  </script>
</body>
</html>`;
}
