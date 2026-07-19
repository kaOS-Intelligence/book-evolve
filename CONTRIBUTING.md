# Contributing

`book-evolve` is a standalone CLI tool, MIT-licensed, built by kaOS Intelligence.

## Prerequisites

- macOS or Linux (Windows users: WSL2)
- Node 18+
- Python 3.10+
- `bash`, `tar`, `rsync` on PATH

## Setup

```bash
git clone https://github.com/kaOS-Intelligence/book-evolve.git
cd book-evolve
npm install
```

## Develop

The Python engine lives in `pipeline-src/` (source of truth). The published
package ships it pre-built as `assets/pipeline/pipeline.tar.gz`.

```bash
npm run build:pipeline   # rebuild the tarball from pipeline-src/
npm run build            # compile TypeScript
npm test                 # e2e CLI tests (includes a Python compile gate)
```

## Safety gates

The tarball build (`scripts/build-pipeline-tarball.sh`) refuses to package
anything that:

1. fails to byte-compile (Python `SyntaxError`),
2. contains personal or internal content (see the blocklist in the script), or
3. contains caches or seeded data (`__pycache__`, `*.pyc`, `cognition.json`).

Any change to `pipeline-src/` must pass all three gates.

## Pull requests

- Keep changes focused; one concern per PR.
- Run `npm test` before pushing.
- New CLI features should add a smoke-test path in `tests/`.

## License

By contributing you agree your contributions are licensed MIT.
