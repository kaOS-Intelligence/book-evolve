"""Embedding service wrapper — Ollama bge-m3.

Hash mode is available ONLY via explicit opt-in with ASI_EVOLVE_HASH_EMBEDDINGS,
for genuine smoke tests. The previous silent hash fallback on Ollama failure
was the root cause of the June 7 cognition bug: it poisoned the FAISS index
with sha256 pseudo-random vectors that had no semantic relationship to the
stored text, which made every retrieval return 0 items. A real failure must
now raise loudly rather than corrupt the vector space.
"""

import hashlib
import os
from typing import List, Union

import numpy as np
import requests


class EmbeddingError(RuntimeError):
    """Raised when the real Ollama bge-m3 path fails and hash fallback is off.

    Refusing to silently hash is the fix for the cognition bug — see the
    module docstring. Callers must either fix Ollama or explicitly opt into
    hash mode via ASI_EVOLVE_HASH_EMBEDDINGS for a smoke test.
    """


class EmbeddingService:
    """Local embedding service backed by Ollama bge-m3 (HTTP)."""

    def __init__(
        self,
        model_name: str = "bge-m3-local",
        dimension: int = 1024,
        device: str = "cpu",
    ):
        """
        Args:
            model_name: Not used directly for Ollama; kept for compatibility.
            dimension: Embedding dimension (bge-m3 = 1024).
            device: Ignored for Ollama; kept for compatibility.
        """
        hash_dim = os.environ.get("ASI_EVOLVE_HASH_EMBEDDINGS")
        if hash_dim:
            # Explicit opt-in smoke-test mode. Hash vectors have no semantic
            # meaning — only use this for plumbing tests, never for a real
            # cognition index that queries must retrieve from.
            self.model = None
            self.dimension = int(hash_dim)
            self._hash_mode = True
            self._ollama_url = "http://127.0.0.1:11434/api/embed"
            self._ollama_model = "bge-m3:latest"
            return

        self._hash_mode = False

        # OLLAMA_BASE_URL / OLLAMA_EMBED_MODEL are the project-wide knobs
        # (shared with the seeder and doctor); ASI_EVOLVE_* win when set.
        ollama_base = (
            os.environ.get("OLLAMA_BASE_URL", "").strip()
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        self._ollama_url = os.environ.get(
            "ASI_EVOLVE_OLLAMA_URL",
            f"{ollama_base}/api/embed",
        )
        self._ollama_model = (
            os.environ.get("ASI_EVOLVE_OLLAMA_MODEL", "").strip()
            or os.environ.get("OLLAMA_EMBED_MODEL", "").strip()
            or "bge-m3:latest"
        )
        self.dimension = int(
            os.environ.get("ASI_EVOLVE_EMBEDDING_DIM", str(dimension))
        )
        self.model = None  # no sentence-transformers

        # Warm-up: verify Ollama is reachable and bge-m3 is loaded. This MUST
        # raise on failure — otherwise init_cognition.py would silently build
        # a poisoned index (the June 7 root cause).
        self._warm()

    def _warm(self) -> None:
        """Verify Ollama is reachable AND bge-m3 can actually encode.

        Raises EmbeddingError if Ollama is unreachable or the bge-m3 model
        is not loaded or returns a bad vector. A warning is not enough:
        index construction must abort cleanly rather than persist
        hash-fallback vectors that queries can never retrieve from.

        The warmup probes the SAME /api/embed endpoint that encode() uses
        (not a separate /api/tags call) so the check actually exercises the
        path that matters. The /api/tags call is kept only to produce a
        helpful error message naming the loaded models.
        """
        tags_url = self._ollama_url.replace("/api/embed", "/api/tags")
        try:
            resp = requests.get(tags_url, timeout=10)
            resp.raise_for_status()
            tags = resp.json()
            model_names = [m.get("name", "") for m in tags.get("models", [])]
            if self._ollama_model not in model_names:
                raise EmbeddingError(
                    f"{self._ollama_model} is not loaded in Ollama "
                    f"(found: {model_names[:5]}...). Pull it with "
                    f"`ollama pull {self._ollama_model}` before building or "
                    f"querying a cognition index."
                )
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(
                f"Cannot reach Ollama at {tags_url}: {e}. "
                "Start Ollama (`ollama serve`) before building or querying "
                "a cognition index. To proceed with hash-mode smoke tests, "
                "set ASI_EVOLVE_HASH_EMBEDDINGS=1024 explicitly."
            ) from e

        # Probe the actual encode endpoint with a tiny string so warmup
        # catches a broken model (NaN vectors, wrong dim, 500s) before any
        # real work begins. This is the check the June 7 index build was
        # missing.
        try:
            probe = self._encode_via_ollama(["warmup probe"], normalize=True)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(
                f"Ollama bge-m3 warmup probe failed at {self._ollama_url}: {e}. "
                f"The model is listed but cannot encode. Reload it "
                f"(`ollama rm {self._ollama_model} && ollama pull "
                f"{self._ollama_model}`) before continuing."
            ) from e
        if probe.shape != (1, self.dimension) or not np.isfinite(probe).all():
            raise EmbeddingError(
                f"Ollama bge-m3 warmup probe returned a bad vector "
                f"(shape={probe.shape}, finite={np.isfinite(probe).all()}). "
                f"The model is reachable but unhealthy."
            )
        print(f"[embedding] Ollama {self._ollama_model} warm and responding.")

    def encode(
        self,
        texts: Union[str, List[str]],
        normalize: bool = True,
    ) -> np.ndarray:
        """
        Encode text into embedding vectors via Ollama bge-m3.

        Args:
            texts: A single string or a list of strings.
            normalize: Whether to L2-normalize embeddings.

        Returns:
            Array of shape `(n, dimension)`.

        Raises:
            EmbeddingError: if Ollama fails and hash fallback is not
                explicitly enabled. The silent hash fallback that poisoned
                the June 7 index is gone on purpose.
        """
        if isinstance(texts, str):
            texts = [texts]

        if self._hash_mode:
            return np.array(
                [_hash_embedding(text, self.dimension, normalize) for text in texts],
                dtype=np.float32,
            )

        # No silent fallback. A real failure must raise so callers know the
        # vector space is broken rather than persisting bad vectors that
        # queries can never retrieve from.
        return self._encode_via_ollama(texts, normalize)

    def _encode_via_ollama(
        self,
        texts: List[str],
        normalize: bool,
    ) -> np.ndarray:
        """Send texts to Ollama /api/embed one at a time (simplest path).

        Raises EmbeddingError on any failure (HTTP, parsing, dimension
        mismatch, NaN vector). A NaN vector from the model would corrupt
        the FAISS index just as badly as a hash vector — detect and refuse.
        """
        vectors = []
        for text in texts:
            try:
                resp = requests.post(
                    self._ollama_url,
                    json={"model": self._ollama_model, "input": text},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                embedding = np.array(data["embeddings"][0], dtype=np.float32)
            except requests.RequestException as e:
                raise EmbeddingError(
                    f"Ollama /api/embed call failed for model "
                    f"{self._ollama_model}: {e}. The cognition index cannot "
                    f"be built or queried without real embeddings."
                ) from e
            except (KeyError, IndexError, ValueError) as e:
                raise EmbeddingError(
                    f"Ollama returned a malformed embedding response: {e}. "
                    f"Check that {self._ollama_model} is healthy."
                ) from e

            if embedding.shape[0] != self.dimension:
                raise EmbeddingError(
                    f"Ollama returned a {embedding.shape[0]}-dim vector but "
                    f"the index expects {self.dimension}. Model "
                    f"{self._ollama_model} may have been replaced."
                )
            if not np.isfinite(embedding).all():
                raise EmbeddingError(
                    f"Ollama returned a vector containing NaN or inf for "
                    f"model {self._ollama_model}. Reload the model "
                    f"(`ollama rm {self._ollama_model} && ollama pull "
                    f"{self._ollama_model}`) before continuing — a NaN vector "
                    f"would corrupt the FAISS index."
                )

            if normalize:
                norm = np.linalg.norm(embedding)
                if norm:
                    embedding = embedding / norm
            vectors.append(embedding)
        return np.array(vectors, dtype=np.float32)

    def get_dimension(self) -> int:
        """Return the embedding dimension."""
        return self.dimension


def _hash_embedding(text: str, dimension: int, normalize: bool) -> np.ndarray:
    """Deterministic smoke-test embedding used when real embeddings fail."""
    values = np.zeros(dimension, dtype=np.float32)
    data = text.encode("utf-8", errors="ignore")
    for i in range(dimension):
        digest = hashlib.sha256(data + i.to_bytes(4, "little")).digest()
        values[i] = (int.from_bytes(digest[:4], "little") / 2**32) - 0.5
    if normalize:
        norm = np.linalg.norm(values)
        if norm:
            values = values / norm
    return values
