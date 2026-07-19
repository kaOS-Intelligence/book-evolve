# @kaos-intelligence/book-evolve

Developmental editor powered by a 3-model evolutionary council. Transforms raw
dictated transcripts into polished book prose in the author's own voice.

## Quick start

```bash
npx @kaos-intelligence/book-evolve scaffold --title "My Book" --dir ./my-book && cd my-book
npx @kaos-intelligence/book-evolve setup --project .
npx @kaos-intelligence/book-evolve evolve --project . --chapter 1
```

Between `setup` and `evolve`, do three things:

1. **Add content** — one `.txt` per chapter in `dictation/` (chapter order =
   filename sort order), and samples of your published writing in
   `author-style/` (your voice anchor).
2. **Point the tool at your models** — copy `.env.ai.example` to `.env.ai` and
   set your endpoint and model ids. The shipped defaults are route aliases for
   a private LiteLLM proxy; they will resolve nowhere else. See
   [Bring your own models](#bring-your-own-models).
3. **Verify** — `doctor` checks the environment, `smoke` does a live
   round-trip through every model you configured:

   ```bash
   npx @kaos-intelligence/book-evolve doctor --project .
   npx @kaos-intelligence/book-evolve smoke --project .
   ```

Prefer a guided setup? Run `npx @kaos-intelligence/book-evolve` for
interactive onboarding, or `npx @kaos-intelligence/book-evolve --web` for a
browser wizard at `http://localhost:3010`.

## How it works

1. **SEED** — your dictation and reference books are embedded into a semantic
   store so the council can retrieve your voice and content.
2. **PROVISION** — each chapter gets an isolated experiment directory.
3. **EVOLVE** — a council of three models each proposes an evolved chapter; a
   judge council scores every candidate on six axes: content fidelity, style
   match, literary quality, structural coherence, readability, and
   evolutionary novelty (near-verbatim copies of the dictation are
   deterministically capped, so a lazy candidate can't score); an analyzer
   extracts lessons; repeat until the target score is reached.
4. **PROMOTE** — the best candidate is written to `output/chapters/` as
   publishable MDX, with `toc.json` and `index.mdx` maintained automatically.

## Requirements

- **macOS or Linux.** The setup flow runs `bash setup.sh` and the CLI drives
  the project venv at `.venv/bin/python3`, so Windows is unsupported natively —
  use [WSL2](https://learn.microsoft.com/windows/wsl/). `bash` and `tar` must
  be on your PATH.
- **Node 18+** and **Python 3.10+**.
- **An OpenAI-compatible chat endpoint** with your council models routed —
  OpenRouter, a local [LiteLLM](https://docs.litellm.ai) proxy, vLLM,
  LM Studio, Ollama's OpenAI endpoint, or any provider's compatible endpoint.
- **[Ollama](https://ollama.com)** with an embedding model for semantic
  retrieval (`ollama pull bge-m3`). Required for `evolve` — the engine
  retrieves your voice and content through embeddings. If you truly can't run
  Ollama, set `ASI_EVOLVE_HASH_EMBEDDINGS=1024` to evolve with degraded
  hash-based retrieval (fine for a test drive, not recommended for a real
  book). `evolve` checks this up front and tells you which option to take.

## Bring your own models

The pipeline talks to one OpenAI-compatible `/chat/completions` endpoint and
needs five model ids: three council seats, a judge, and a fast model. The
default ids (`deepseek-v4-pro-cloud`, `mimo-v2.5-pro-cloud`, `glm-5.2-cloud`,
`deepseek-v4-flash-cloud`) are naming conventions from the author's own
LiteLLM proxy config — **you must override them with model ids your endpoint
actually serves.** Three genuinely different models give the best editorial
diversity, but three copies of one strong model also works.

### Example: OpenRouter (hosted, one API key)

Create `.env.ai` in your project:

```bash
LITELLM_BASE_URL=https://openrouter.ai/api/v1
LITELLM_API_KEY=sk-or-v1-...

COUNCIL_MODEL_1=deepseek/deepseek-chat
COUNCIL_MODEL_2=anthropic/claude-sonnet-4.5
COUNCIL_MODEL_3=google/gemini-2.5-pro
JUDGE_MODEL=anthropic/claude-sonnet-4.5
FAST_MODEL=google/gemini-2.5-flash
```

Model ids drift as providers ship new versions — browse
[openrouter.ai/models](https://openrouter.ai/models) for current ids, then run
`smoke` to confirm every seat answers.

### Example: fully local (Ollama, no API key)

Ollama exposes an OpenAI-compatible endpoint at `/v1`. Pull three chat models
plus the embedder, then:

```bash
LITELLM_BASE_URL=http://127.0.0.1:11434/v1
LITELLM_API_KEY=

COUNCIL_MODEL_1=qwen3:32b
COUNCIL_MODEL_2=llama3.3:70b
COUNCIL_MODEL_3=gemma3:27b
JUDGE_MODEL=qwen3:32b
FAST_MODEL=llama3.2:3b

OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_EMBED_MODEL=bge-m3:latest
```

The same shape works for vLLM (`http://127.0.0.1:8000/v1`) or LM Studio
(`http://127.0.0.1:1234/v1`) — set `LITELLM_BASE_URL` to the server and the
model variables to whatever ids it serves.

### Example: LiteLLM proxy (mix providers per seat)

A [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start) lets you
route each council seat to a different provider behind one endpoint. Point
`LITELLM_BASE_URL` at the proxy (default `http://127.0.0.1:4000/v1`) and set
the model variables to your route names. If the proxy has a master key, put it
in `LITELLM_API_KEY` or write it to `~/.litellm-master-key`.

## Configuration

Everything is environment-driven with sensible defaults — no hardcoding.

**`.env.ai` is loaded automatically.** Every command (`doctor`, `smoke`,
`seed`, `evolve`, and the default launcher) reads `<project>/.env.ai` before
it runs, so your model configuration lives in one file. Standard dotenv
semantics: values already exported in your shell win over the file. A
commented `.env.ai.example` is written into every scaffolded project.

| Variable | Default | Purpose |
|---|---|---|
| `LITELLM_BASE_URL` | `http://127.0.0.1:4000/v1` | Any OpenAI-compatible chat endpoint |
| `LITELLM_API_KEY` | `~/.litellm-master-key` if present, else `EMPTY` | Endpoint auth (bearer token) |
| `COUNCIL_MODEL_1..3` | `deepseek-v4-pro-cloud` / `mimo-v2.5-pro-cloud` / `glm-5.2-cloud` | The 3 council seats — override these |
| `JUDGE_MODEL` | `deepseek-v4-pro-cloud` | Scoring judge + manager |
| `FAST_MODEL` | `deepseek-v4-flash-cloud` | Engineer + analyzer roles (high-volume, cheap) |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Embedding endpoint (optional) |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | Embedding model |

Advanced variables (rarely needed — the CLI sets the first three per run from
your project and `config.yaml`):

| Variable | Default | Purpose |
|---|---|---|
| `BOOK_EVOLUTION_OUTPUT_DIR` | `<project>/output` (set by the CLI) | Where promoted chapters land |
| `BOOK_EVOLUTION_TITLE` / `_AUTHOR` / `_SUBTITLE` | from `config.yaml` (set by the CLI) | Book metadata on the cover and index |
| `BOOK_EVOLUTION_OUTPUT_ROOT` | unset | Canonical promoted-output root when embedding the pipeline in a larger system |
| `BOOK_EVOLUTION_CONTENT_ID` | UUID derived from the title | Stable content id used in the output folder name and MDX frontmatter |
| `ASI_EVOLVE_ACTIVITY_STREAM` | `<project>/experiments/activity_stream.jsonl` | Path of the live progress event stream |
| `ASI_EVOLVE_HASH_EMBEDDINGS` | unset | Set to `1024` to evolve without Ollama using degraded hash retrieval |

The same values can be set per-project in `experiments/book_evolution/config.yaml`
(which supports `${VAR:-default}` placeholders), or per-run via the shell.
Precedence: shell exports, then `.env.ai`, then `config.yaml` defaults.

## Commands

| Command | Purpose |
|---|---|
| `book-evolve` | Interactive onboarding; relaunches an existing project if one is found. `--web` opens the browser wizard on port 3010; `--skip-onboard` uses defaults; `--output <dir>` sets the project location. |
| `book-evolve scaffold` | Create (or `--force` re-create) a project. `--title`, `--author`, `--goal`, `--dir`. |
| `book-evolve setup --project .` | Create the Python venv and install pipeline dependencies (one time). |
| `book-evolve doctor --project .` | Verify Python, venv, pipeline files, model endpoint, embeddings, and content. Every failure prints the exact fix. Exits 1 on failure. |
| `book-evolve smoke --project .` | Live round-trip: one tiny completion per unique council/judge/fast model plus an embedding. Run this before your first evolution. |
| `book-evolve seed --project .` | Manually seed the cognition store (`--dictation`, `--reference`, `--reference-source`). `evolve` seeds automatically — you only need this for custom flows. |
| `book-evolve evolve --project . --chapter 1` | Run the full pipeline: seed, provision, evolve, promote. |

All subcommands accept `--project <dir>` and default to the current
directory; `scaffold --dir` and the bare launcher's `--output` default to
`./book-project`.

## Evolution controls

```bash
book-evolve evolve --project . \
  --chapter 1 --end-chapter 20 \   # chapter range
  --target-score 0.95 \            # stop a chapter early at this judge score
  --patience 8 \                   # stop after N no-improvement steps
  --max-steps 10 \                 # hard ceiling per chapter
  --fresh                          # wipe prior state instead of resuming
```

Each chapter takes roughly 2–15 minutes depending on complexity and your
models' speed. Evolved chapters land in `output/chapters/` as MDX, ready for
any Markdown-based publishing pipeline.

## Observability

Every run appends progress events — round start, candidate produced, judge
score, lesson extracted — to an append-only JSONL activity stream at
`<project>/experiments/activity_stream.jsonl`. Tail it to watch a run live or
point a UI at it:

```bash
tail -f experiments/activity_stream.jsonl | jq .
```

Set `ASI_EVOLVE_ACTIVITY_STREAM` to move the stream. Event writes are
best-effort by design — a progress event can never take down a run.

## Development

The canonical home for this package is
[kaOS-Intelligence/book-evolve](https://github.com/kaOS-Intelligence/book-evolve).
The Python engine's source of truth is `pipeline-src/` in the repo; the
published package ships it pre-built as `assets/pipeline/pipeline.tar.gz`.

```bash
pnpm build:pipeline   # rebuild assets/pipeline/pipeline.tar.gz from pipeline-src/
pnpm build            # compile TypeScript
pnpm test             # e2e CLI tests (includes a Python compile gate)
```

The tarball build refuses to package anything that fails to byte-compile or
contains personal content.

## License

MIT © kaOS Intelligence Inc.
