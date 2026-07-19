"""Core pipeline orchestration for ASI-Evolve.

The pipeline wires together the manager, researcher, engineer, and analyzer
agents, then executes the evolutionary loop in sequential or parallel mode.
"""
import json
import os
import sys
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from ..utils.config import load_config
from ..utils.llm import create_llm_client
from ..utils.logger import init_logger
from ..utils.prompt import PromptManager
from ..utils.structures import Node, CognitionItem
from ..utils import BestSnapshotManager
from ..database import Database
from ..cognition import Cognition
from ..experiment_supabase import SupabaseMirror, emit_evolve_event

from .researcher import Researcher
from .engineer import Engineer
from .analyzer import Analyzer
from .manager import Manager


def _odyssey_rerank_items(
    items: list[CognitionItem],
    query: str,
    logger: Any = None,
) -> None:
    """Reorder cognition items in-place via broker /rerank cross-encoder.

    Graceful fallback: any error leaves FAISS order intact.
    """
    broker_url = os.environ.get("RERANK_BROKER_URL", "")
    broker_key = os.environ.get("RERANK_BROKER_KEY", "")
    if not broker_url:
        # No external reranker configured — keep FAISS order. This is the
        # normal standalone path; a cross-encoder rerank service is optional.
        return

    candidates = [{"content": c.content} for c in items]

    payload = json.dumps({
        "query": query,
        "candidates": candidates,
        "corpus": "book_evolution",
        "top_k": min(len(items), 8),
    }).encode()

    headers = {"Content-Type": "application/json"}
    if broker_key:
        headers["Authorization"] = f"Bearer {broker_key}"

    req = urllib.request.Request(
        f"{broker_url}/rerank/cross_encoder",
        data=payload,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
    except Exception as e:
        if logger:
            logger.warning(f"rerank call failed, keeping FAISS order: {e}")
        return

    ranked = result.get("results") or result.get("ranked")
    if not result.get("ok") or not ranked:
        return

    # Reorder items in-place by cross-encoder score (descending)
    ranked_indices = [r["index"] for r in ranked]
    reranked = [items[i] for i in ranked_indices if 0 <= i < len(items)]
    # Append any items beyond top_k in original order
    for i, item in enumerate(items):
        if i not in ranked_indices:
            reranked.append(item)
    items[:] = reranked

    if logger:
        via = (result.get("meta") or {}).get("via") or result.get("via")
        logger.info(
            f"Reranked {len(ranked_indices)} cognition items via {via}"
        )


def _odyssey_load_greek(cog_dir: Path, book_n: int) -> Optional[str]:
    """Load the Greek source text for ``book_n`` from the cognition store.

    Mirrors the evaluator's loader so the council and the judge anchor to the
    same Perseus/Murray Greek. Returns ``None`` on any miss — the researcher
    template degrades gracefully to retrieval-only grounding.
    """
    import re as _re

    cognition_path = Path(cog_dir) / "cognition.json"
    if not cognition_path.exists():
        return None
    try:
        with open(cognition_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    for item in data.get("items", {}).values():
        meta = item.get("metadata", {})
        if meta.get("topic") == "greek_source_text" and meta.get("book_number") == book_n:
            content = item.get("content", "")
            if ":\n\n" in content:
                _, body = content.split(":\n\n", 1)
            else:
                body = content
            body = body.replace("<Line n=", "").replace("<GreekLine n=", "")
            for tag in ["</Line>", "</GreekLine>", "</Chapter>", "</BilingualChapter>"]:
                body = body.replace(tag, "")
            body = _re.sub(r'"[^"]*">', " ", body)
            return body.strip()
    return None


def _seventy_one_load_source(cog_dir: Path) -> Optional[str]:
    """Load the source chapter text for a Seventy-One translation run.

    Mirrors the generic evaluator's loader (topic == "source_text") so the
    council and the judge anchor to the same source. Returns ``None`` on any
    miss — the researcher template degrades gracefully to retrieval-only
    grounding.
    """
    cognition_path = Path(cog_dir) / "cognition.json"
    if not cognition_path.exists():
        return None
    try:
        with open(cognition_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    for item in data.get("items", {}).values():
        meta = item.get("metadata", {})
        if meta.get("topic") == "source_text":
            content = str(item.get("content", "")).strip()
            if content:
                return content
    return None


def _book_evolution_load_dictation(cog_dir: Path) -> Optional[str]:
    """Load the dictation transcript from the cognition store.

    Returns the full dictation text. Returns ``None`` on any miss —
    the researcher template degrades gracefully.
    """
    cognition_path = Path(cog_dir) / "cognition.json"
    if not cognition_path.exists():
        return None
    try:
        with open(cognition_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    for item in data.get("items", {}).values():
        meta = item.get("metadata", {})
        if meta.get("topic") == "dictation_transcript":
            return item.get("content", "").strip()
    return None


def _book_evolution_load_style_samples(cog_dir: Path) -> list[dict]:
    """Load all author style reference samples from the cognition store."""
    cognition_path = Path(cog_dir) / "cognition.json"
    if not cognition_path.exists():
        return []
    try:
        with open(cognition_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    samples: list[dict] = []
    for item in data.get("items", {}).values():
        meta = item.get("metadata", {})
        if meta.get("topic") == "author_style_sample":
            samples.append(
                {
                    "content": item.get("content", ""),
                    "metadata": meta,
                }
            )
    return samples


def _cognition_items_as_chunks(items: list[CognitionItem]) -> list[Any]:
    """Adapt cognition items to the chunk shape broker discoverer scoring expects."""
    chunks: list[Any] = []

    class _CogChunk:
        __slots__ = ("content", "score", "corpus", "source_path", "chunk_index", "metadata")

        def __init__(
            self,
            content: str,
            score: float,
            corpus: str,
            source_path: str,
            chunk_index: int,
            metadata: dict[str, Any],
        ) -> None:
            self.content = content
            self.score = score
            self.corpus = corpus
            self.source_path = source_path
            self.chunk_index = chunk_index
            self.metadata = metadata

    for idx, item in enumerate(items):
        meta = dict(item.metadata or {})
        chunks.append(
            _CogChunk(
                content=item.content,
                score=float(meta.get("_faiss_score", 1.0 - idx * 0.01)),
                corpus=str(meta.get("corpus") or "odyssey_press"),
                source_path=item.source or item.id or f"cognition-{idx}",
                chunk_index=idx,
                metadata=meta,
            )
        )
    return chunks


def _odyssey_discoverer_items(
    items: list[CognitionItem],
    *,
    logger: Any = None,
) -> None:
    """Optional learned-reranker overlay — not shipped with the standalone
    build. The cross-encoder / FAISS ordering from the previous stage is
    already the final order here. Kept as a stable extension point.
    """
    return


class Pipeline:
    """Coordinate a resumable ASI-Evolve experiment.

    The pipeline is responsible for loading configuration, initializing shared
    services, running each evolution step, and keeping enough state on disk to
    resume an interrupted experiment.
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        experiment_name: Optional[str] = None,
    ):
        if experiment_name is None:
            from ..utils.config import load_config as _load_config
            temp_config = _load_config(config_path=config_path)
            experiment_name = temp_config.get("experiment_name", "default")
        
        self.experiment_name = experiment_name
        
        self.config = load_config(config_path=config_path, experiment_name=experiment_name)
        self.config["experiment_name"] = experiment_name
        
        base_dir = Path(__file__).parent.parent / "experiments"
        self.experiment_dir = base_dir / self.experiment_name
        self.experiment_dir.mkdir(parents=True, exist_ok=True)

        self.steps_dir = self.experiment_dir / "steps"
        self.steps_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = self.experiment_dir / "pipeline_state.json"
        
        log_config = self.config.get("logging", {})
        wandb_config = log_config.get("wandb", {})
        if wandb_config:
            wandb_config = wandb_config.copy()
            wandb_config["run_name"] = self.experiment_name
            wandb_config["config"] = self.config
        
        self.logger = init_logger(
            name="evolve",
            log_dir=self.experiment_dir / "logs",
            level=log_config.get("level", "INFO"),
            console=log_config.get("console", True),
            wandb_config=wandb_config,
        )
        
        self.llm = create_llm_client(self.config)
        
        prompt_dir = self.experiment_dir / "prompts"
        self.prompt_manager = PromptManager(prompt_dir)
        
        db_config = self.config.get("database", {})
        sampling_config = db_config.get("sampling", {})
        algorithm = sampling_config.get("algorithm", "ucb1")
        
        sampling_kwargs = {}
        if algorithm == "ucb1":
            sampling_kwargs["c"] = sampling_config.get("ucb1_c", 1.414)
        elif algorithm.startswith("island"):
            island_config = sampling_config.get(algorithm, sampling_config.get("island", {}))
            sampling_kwargs = {
                "num_islands": island_config.get("num_islands", 5),
                "migration_interval": island_config.get("migration_interval", 10),
                "migration_rate": island_config.get("migration_rate", 0.1),
                "exploration_ratio": island_config.get("exploration_ratio", 0.2),
                "exploitation_ratio": island_config.get("exploitation_ratio", 0.3),
                "feature_dimensions": island_config.get("feature_dimensions", []),
                "feature_bins": island_config.get("feature_bins", 10),
            }
        
        self.database = Database(
            storage_dir=self.experiment_dir / db_config.get("storage_dir", "database_data"),
            embedding_model=db_config.get("embedding", {}).get(
                "model", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            embedding_dim=db_config.get("embedding", {}).get("dimension", 384),
            sampling_algorithm=algorithm,
            sampling_kwargs=sampling_kwargs,
            max_size=db_config.get("max_size"),
        )
        
        cog_config = self.config.get("cognition", {})
        self._cog_storage_dir = self.experiment_dir / cog_config.get("storage_dir", "cognition_data")
        self.cognition = Cognition(
            storage_dir=self.experiment_dir / cog_config.get("storage_dir", "cognition_data"),
            embedding_model=cog_config.get("embedding", {}).get(
                "model", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            embedding_dim=cog_config.get("embedding", {}).get("dimension", 384),
            retrieval_top_k=cog_config.get("retrieval", {}).get("top_k", 5),
            score_threshold=cog_config.get("retrieval", {}).get("score_threshold", 0.5),
        )
        
        pipeline_config = self.config.get("pipeline", {})
        agents_config = pipeline_config.get("agents", {})
        
        self.use_manager = agents_config.get("manager", False)
        self.use_researcher = agents_config.get("researcher", True)
        self.use_engineer = agents_config.get("engineer", True)
        self.use_analyzer = agents_config.get("analyzer", True)
        
        self.researcher_config = pipeline_config.get("researcher", {})
        # Merge api role_models into researcher_config so the council resolver
        # has access to the full model routing configuration.
        if "api" in self.config:
            api_roles = self.config["api"].get("role_models", {})
            if "role_models" not in self.researcher_config:
                self.researcher_config["role_models"] = api_roles
        
        self.manager = Manager(self.llm, self.prompt_manager) if self.use_manager else None
        self.researcher = Researcher(self.llm, self.prompt_manager, self.researcher_config) if self.use_researcher else None
        self.engineer = Engineer(self.llm, self.prompt_manager) if self.use_engineer else None
        self.analyzer = Analyzer(self.llm, self.prompt_manager) if self.use_analyzer else None
        
        self.max_retries = pipeline_config.get("max_retries", {})
        
        judge_config = pipeline_config.get("judge", {})
        self.judge_enabled = judge_config.get("enabled", False)
        self.judge_ratio = judge_config.get("ratio", 0.2)
        
        parallel_config = pipeline_config.get("parallel", {})
        self.num_workers = parallel_config.get("num_workers", 1)
        self.step_lock = Lock()
        
        self.engineer_timeout = pipeline_config.get("engineer_timeout", 3600)
        
        self.sample_n = pipeline_config.get("sample_n", 3)
        
        self.step = 0
        self.manager_initialized = False
        self._load_state()
        
        self.is_resume = self.step > 0 or len(self.database) > 0
        if self.is_resume:
            self.logger.info(
                f"Resuming experiment '{self.experiment_name}' from step {self.step} "
                f"(database: {len(self.database)} nodes, cognition: {len(self.cognition)} items)"
            )
        else:
            self.logger.info(f"Starting new experiment: {self.experiment_name}")
        
        self.initial_node_created = False

        self.best_snapshot = BestSnapshotManager(self.steps_dir, logger=self.logger)
        self.best_snapshot.init_from_nodes(self.database.get_all())

        self.mirror = SupabaseMirror(self.experiment_name, seat=self.experiment_name)
        self.mirror.ensure_experiment(config=self.config)
    
    def _load_state(self):
        """Restore pipeline progress from disk or infer it from existing data."""
        import json
        
        if not self.state_file.exists():
            if len(self.database) > 0:
                max_id = max(n.id for n in self.database.get_all() if n.id is not None)
                self.step = max_id + 1
                prompt_dir = self.experiment_dir / "prompts"
                if prompt_dir.exists() and any(prompt_dir.glob("*.jinja2")):
                    self.manager_initialized = True
            return
        
        with open(self.state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
        
        self.step = state.get("step", 0)
        self.manager_initialized = state.get("manager_initialized", False)
    
    def _save_state(self):
        """Persist the current pipeline progress to the experiment directory."""
        state = {
            "step": self.step,
            "manager_initialized": self.manager_initialized,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def run_step(
        self,
        task_description: Optional[str] = None,
        eval_script: Optional[str] = None,
        sample_n: Optional[int] = None,
    ) -> Optional[Node]:
        """Run one evolutionary step and return the resulting node, if any."""
        with self.step_lock:
            self.step += 1
            current_step = self.step
            self._save_state()
        
        self.logger.info(f"=== Step {current_step} ===")
        emit_evolve_event(
            "evolve.round.start",
            {
                "experiment": self.experiment_name,
                "round": current_step,
                "parent_id": None,
                "candidate_id": None,
            },
        )
        
        if sample_n is None:
            sample_n = self.sample_n
        
        try:
            if task_description is None:
                input_file = self.experiment_dir / "input.md"
                if input_file.exists():
                    task_description = input_file.read_text(encoding="utf-8")
                else:
                    self.logger.error("No task description provided")
                    return None
            
            if self.use_manager and not self.manager_initialized:
                self._run_manager(task_description)
                self.manager_initialized = True
                self._save_state()
                self.prompt_manager = PromptManager(self.experiment_dir / "prompts")
                if self.researcher:
                    self.researcher.prompt_manager = self.prompt_manager
                if self.analyzer:
                    self.analyzer.prompt_manager = self.prompt_manager
            
            context_nodes = self.database.sample(sample_n)
            parent_ids = [n.id for n in context_nodes if n.id is not None]
            self.logger.info(f"Sampled {len(context_nodes)} context nodes")
            
            cognition_items = []
            if context_nodes:
                for node in context_nodes:
                    if node.analysis:
                        items = self.cognition.search(node.analysis, top_k=2)
                        cognition_items.extend(items)
                    else:
                        items = self.cognition.search(node.motivation, top_k=2)
                        cognition_items.extend(items)
            # Resolve which Odyssey book we are evolving (env-driven, default 1).
            # Non-odyssey experiments skip the literary-translation retrieval and
            # Greek-anchor injection entirely.
            is_odyssey = self.experiment_name.startswith("odyssey")
            is_book_evolution = self.experiment_name.startswith("book_evolution")
            is_seventy_one = self.experiment_name.startswith("seventy_one")
            book_n = 1
            if is_odyssey:
                try:
                    book_n = int(os.environ.get("ODYSSEY_BOOK_N", "1"))
                except ValueError:
                    book_n = 1

            # Also retrieve reference translations and Greek source directly
            # by searching for the per-book "Greek source text" and "translation" topics.
            if is_odyssey:
                for query in (
                    f"Book {book_n} Greek source text Homer Odyssey",
                    f"English translation Odyssey Book {book_n} reference",
                ):
                    direct_items = self.cognition.search(query, top_k=3)
                    cognition_items.extend(direct_items)
            self.logger.info(f"Retrieved {len(cognition_items)} cognition items")

            # Load the Greek anchor for this book so the council prompt's
            # {% if greek_source %} branch is actually populated (was a dead
            # branch — researcher never received greek_source before).
            greek_source = None
            if is_odyssey:
                greek_source = _odyssey_load_greek(self._cog_storage_dir, book_n)
                if greek_source:
                    self.logger.info(
                        f"Greek anchor loaded for Book {book_n} "
                        f"({len(greek_source)} chars)"
                    )
                else:
                    self.logger.warning(
                        f"No Greek anchor found for Book {book_n}; "
                        "council will rely on retrieval only"
                    )

            # Load the source chapter anchor for Seventy-One translation runs
            # so the researcher template's {% if source_text %} branch is
            # populated — council and judge anchor to the same text.
            source_text = None
            if is_seventy_one:
                source_text = _seventy_one_load_source(self._cog_storage_dir)
                if source_text:
                    self.logger.info(
                        f"Source anchor loaded ({len(source_text)} chars)"
                    )
                else:
                    self.logger.warning(
                        "No source_text found in cognition store; "
                        "council will rely on retrieval only"
                    )

            # Load dictation transcript and style samples for book-evolution experiments.
            dictation_source = None
            style_samples = []
            if is_book_evolution:
                dictation_source = _book_evolution_load_dictation(self._cog_storage_dir)
                style_samples = _book_evolution_load_style_samples(self._cog_storage_dir)
                if dictation_source:
                    self.logger.info(
                        f"Dictation loaded ({len(dictation_source)} chars)"
                    )
                else:
                    self.logger.warning(
                        "No dictation transcript found; council will rely on retrieval only"
                    )
                if style_samples:
                    self.logger.info(
                        f"Style samples loaded: {len(style_samples)} samples"
                    )
                else:
                    self.logger.warning("No style samples found")

            # -- cross-encoder rerank pass -----------------------------------
            # Precision-reorder cognition items via the broker's
            # BGE-Reranker-v2-M3 endpoint. Falls back silently on any
            # error — the FAISS-ranked order survives.
            if cognition_items and task_description:
                _odyssey_rerank_items(cognition_items, task_description, self.logger)
                _odyssey_discoverer_items(cognition_items, logger=self.logger)

            if not self.researcher:
                self.logger.error("Researcher not enabled")
                return None
            
            step_dir = self.steps_dir / f"step_{current_step}"
            step_dir.mkdir(parents=True, exist_ok=True)
            
            if self.researcher:
                self.researcher.set_step_dir(step_dir)
            if self.analyzer:
                self.analyzer.set_step_dir(step_dir)
            if self.engineer:
                self.engineer.set_step_dir(step_dir)
            
            base_code = None
            if self.researcher_config.get("diff_based_evolution", True) and context_nodes:
                base_code = context_nodes[0].code
                self.logger.info(f"Using base code from: {context_nodes[0].name}")
            
            try:
                researcher_results = self.researcher.run(
                    task_description=task_description,
                    context_nodes=context_nodes,
                    cognition_items=cognition_items,
                    base_code=base_code,
                    greek_source=greek_source,
                    dictation_source=dictation_source,
                    style_samples=style_samples,
                    source_text=source_text,
                )
                # researcher_results is now a list of candidate dicts (council mode)
                if isinstance(researcher_results, dict):
                    researcher_results = [researcher_results]
            except Exception as e:
                self.logger.error(f"Researcher failed: {type(e).__name__}: {e}")
                self.logger.error(traceback.format_exc())
                return None

            results_for_analyzer = []
            best_node = None
            best_score = -1.0
            
            for ri, researcher_result in enumerate(researcher_results):
                node_name = researcher_result.get("name", f"node_{current_step}_{ri}")
                model_tag = researcher_result.get("model", "?")
                self.logger.info(f"  Candidate [{ri+1}/{len(researcher_results)}]: {node_name} (model={model_tag})")
                
                sub_node = Node(
                    name=node_name,
                    created_at=datetime.now().isoformat(),
                    parent=parent_ids,
                    motivation=researcher_result.get("motivation", ""),
                    code=researcher_result.get("code", ""),
                )
                emit_evolve_event(
                    "evolve.round.candidate",
                    {
                        "experiment": self.experiment_name,
                        "round": current_step,
                        "parent_ids": parent_ids,
                        "candidate_name": sub_node.name,
                        "motivation": sub_node.motivation,
                        "code_excerpt": sub_node.code[:1200],
                        "model": model_tag,
                    },
                )
                
                sub_engineer = {}
                
                if self.engineer and (eval_script or self.judge_enabled):
                    try:
                        sub_engineer = self.engineer.run(
                            code=sub_node.code,
                            experiment_dir=step_dir,
                            eval_script=eval_script,
                            timeout=self.engineer_timeout,
                            task_description=task_description,
                            judge_enabled=self.judge_enabled,
                            judge_ratio=self.judge_ratio,
                        )
                        
                        sub_node.results = {k: v for k, v in sub_engineer.items() if k != "temp"}
                        
                        sub_node.score = sub_engineer.get("score", 0.0)
                        sub_node.meta_info["runtime"] = sub_engineer.get("runtime")
                        sub_node.meta_info["success"] = sub_engineer.get("success")
                        sub_node.meta_info["eval_score"] = sub_engineer.get("eval_score", 0.0)
                        # Judge robustness: a `judge_failed` result is the judge
                        # being unavailable (refusal/unparseable), NOT a real 0.0
                        # for the candidate. Carry the flag so the step can be
                        # excluded from the convergence/patience signal.
                        sub_node.meta_info["judge_failed"] = bool(sub_engineer.get("judge_failed"))
                        if sub_engineer.get("guard_trip"):
                            sub_node.meta_info["guard_trip"] = sub_engineer.get("guard_trip")
                        if self.judge_enabled:
                            sub_node.meta_info["judge_score"] = sub_engineer.get("judge_score")
                        
                        if not sub_engineer.get("success"):
                            sub_node.meta_info["error"] = sub_engineer.get("error")
                        
                        if sub_node.score > best_score:
                            best_score = sub_node.score
                            best_node = sub_node
                            
                    except Exception as e:
                        self.logger.error(f"Engineer failed for {node_name}: {type(e).__name__}: {e}")
                        sub_node.meta_info["success"] = False
                        sub_node.meta_info["error"] = str(e)
                        sub_node.score = 0.0
                
                results_for_analyzer.append({
                    "node": sub_node,
                    "engineer_result": sub_engineer,
                    "researcher_result": researcher_result,
                })
            
            if best_node is None:
                self.logger.error("No valid candidates from council")
                return None
            
            # Use the best-scored candidate as the primary node for this step
            node = best_node
            engineer_result = next(
                (ra["engineer_result"] for ra in results_for_analyzer if ra["node"] is best_node),
                {},
            )

            # Mark the whole step as judge-unscored if NO candidate with real
            # content got a genuine judge score this round (every seat either
            # produced nothing or had the judge refuse/fail). _run_sequential
            # uses this to avoid burning the patience counter on a step where
            # the judge — not the translation — was the failure.
            step_has_real_score = any(
                (ra["node"].code or "").strip()
                and ra["engineer_result"].get("success", False)
                and not ra["engineer_result"].get("judge_failed", False)
                for ra in results_for_analyzer
            )
            node.meta_info["judge_failed_step"] = not step_has_real_score
            
            if self.analyzer:
                try:
                    best_sampled_node = None
                    if context_nodes:
                        best_sampled_node = max(context_nodes, key=lambda n: n.score)
                        self.logger.info(f"Best sampled node for comparison: {best_sampled_node.name} (score={best_sampled_node.score:.4f})")
                    
                    analyzer_result = self.analyzer.run(
                        code=node.code,
                        results=engineer_result,
                        task_description=task_description,
                        best_sampled_node=best_sampled_node,
                    )
                    node.analysis = analyzer_result.get("analysis", "")
                except Exception as e:
                    self.logger.error(f"Analyzer failed: {type(e).__name__}: {e}")
                    self.logger.error(traceback.format_exc())
                    node.analysis = f"Analysis failed: {e}"
            else:
                if "temp" in engineer_result:
                    node.results["temp"] = engineer_result["temp"]
            
            # Store ALL council candidates in the database, not just the best one
            all_node_ids = []
            for ra in results_for_analyzer:
                sub_node = ra["node"]
                sub_engineer = ra["engineer_result"]
                if not sub_node.code or not sub_node.code.strip():
                    continue
                
                if self.analyzer and sub_node is node:
                    # Only run analyzer on the best node
                    pass
                else:
                    sub_node.analysis = node.analysis  # share the lesson from best
                
                try:
                    sid = self.database.add(sub_node)
                    all_node_ids.append(sid)
                    self.logger.info(f"  Added to database: {sid} ({sub_node.name}, score={sub_node.score:.4f})")
                except Exception as e:
                    self.logger.warning(f"  Failed to add {sub_node.name} to database: {e}")
            
            node_id = all_node_ids[0] if all_node_ids else None
            if node_id is None:
                return None
            emit_evolve_event(
                "evolve.round.score",
                {
                    "experiment": self.experiment_name,
                    "round": current_step,
                    "candidate_id": node_id,
                    "score": node.score,
                    "metrics": node.results,
                },
            )
            emit_evolve_event(
                "evolve.round.lesson",
                {
                    "experiment": self.experiment_name,
                    "round": current_step,
                    "candidate_id": node_id,
                    "lesson": node.analysis,
                },
            )
            
            self.logger.log_node(node, current_step, database=self.database)
            self.mirror.mirror_round(node, current_step, step_dir)

            self.best_snapshot.update_if_better(
                node,
                step_name=f"step_{current_step}",
                source_step_dir=step_dir,
            )
            
            return node
            
        except Exception as e:
            self.logger.error(f"Step {current_step} failed with unexpected error:")
            self.logger.error(f"{type(e).__name__}: {e}")
            self.logger.error(traceback.format_exc())
            return None
    
    def _run_manager(self, task_description: str):
        self.logger.info("[Manager] Generating prompts...")
        
        eval_file = self.experiment_dir / "eval_criteria.md"
        eval_criteria = ""
        if eval_file.exists():
            eval_criteria = eval_file.read_text(encoding="utf-8")
        
        self.manager.run(
            task_description=task_description,
            eval_criteria=eval_criteria,
            prompt_dir=self.experiment_dir / "prompts",
        )
    
    def run(
        self,
        max_steps: int = 10,
        task_description: Optional[str] = None,
        eval_script: Optional[str] = None,
        sample_n: Optional[int] = None,
        target_score: Optional[float] = None,
        patience: Optional[int] = None,
    ):
        """Run the pipeline for ``max_steps`` in sequential or parallel mode.

        Convergence (sequential mode only):
          * ``target_score`` — stop early once the best node reaches this score.
          * ``patience`` — stop early after this many consecutive steps with no
            improvement to the best score.
        Both default to ``None`` (disabled), preserving prior fixed-step
        behavior for every experiment that does not opt in.
        """
        if sample_n is None:
            sample_n = self.sample_n
        
        if not self.is_resume and not self.initial_node_created:
            self._create_initial_node(task_description, eval_script)
        
        if self.num_workers == 1:
            self._run_sequential(
                max_steps,
                task_description,
                eval_script,
                sample_n,
                target_score=target_score,
                patience=patience,
            )
        else:
            self._run_parallel(max_steps, task_description, eval_script, sample_n)

    def _create_initial_node(
        self,
        task_description: Optional[str],
        eval_script: Optional[str],
    ) -> None:
        """Evaluate and register an ``initial_program`` seed before evolution."""
        initial_program_file = self.experiment_dir / "initial_program"
        if not initial_program_file.exists():
            return
        
        self.logger.info("Found initial_program, creating initial node before evolution steps")
        
        if task_description is None:
            input_file = self.experiment_dir / "input.md"
            if input_file.exists():
                task_description = input_file.read_text(encoding="utf-8")
            else:
                task_description = ""
        
        initial_code = initial_program_file.read_text(encoding="utf-8")
        
        step_dir = self.steps_dir / "step_0_initial"
        step_dir.mkdir(parents=True, exist_ok=True)
        
        if self.researcher:
            self.researcher.set_step_dir(step_dir)
        if self.analyzer:
            self.analyzer.set_step_dir(step_dir)
        if self.engineer:
            self.engineer.set_step_dir(step_dir)
        
        node = Node(
            name="initial_program",
            created_at=datetime.now().isoformat(),
            parent=[],
            motivation="Initial program provided by user",
            code=initial_code,
        )
        
        engineer_result: Dict[str, Any] = {}
        
        if self.engineer and (eval_script or self.judge_enabled):
            try:
                engineer_result = self.engineer.run(
                    code=node.code,
                    experiment_dir=step_dir,
                    eval_script=eval_script,
                    timeout=self.engineer_timeout,
                    task_description=task_description or "",
                    judge_enabled=self.judge_enabled,
                    judge_ratio=self.judge_ratio,
                )
                
                node.results = {k: v for k, v in engineer_result.items() if k != "temp"}
                
                node.score = engineer_result.get("score", 0.0)
                node.meta_info["runtime"] = engineer_result.get("runtime")
                node.meta_info["success"] = engineer_result.get("success")
                node.meta_info["eval_score"] = engineer_result.get("eval_score", 0.0)
                if self.judge_enabled:
                    node.meta_info["judge_score"] = engineer_result.get("judge_score")
                
                if not engineer_result.get("success"):
                    node.meta_info["error"] = engineer_result.get("error")
            
            except Exception as e:
                self.logger.error(f"Initial Engineer failed: {type(e).__name__}: {e}")
                self.logger.error(traceback.format_exc())
                node.meta_info["success"] = False
                node.meta_info["error"] = str(e)
                node.score = 0.0
                engineer_result = {}
        
        if self.analyzer:
            try:
                analyzer_result = self.analyzer.run(
                    code=node.code,
                    results=engineer_result,
                    task_description=task_description or "",
                )
                node.analysis = analyzer_result.get("analysis", "")
            except Exception as e:
                self.logger.error(f"Initial Analyzer failed: {type(e).__name__}: {e}")
                self.logger.error(traceback.format_exc())
                node.analysis = f"Analysis failed: {e}"
        
        node_id = self.database.add(node)
        self.logger.info(f"Added initial node {node_id}: {node.name} (score={node.score:.4f})")
        emit_evolve_event(
            "evolve.round.score",
            {
                "experiment": self.experiment_name,
                "round": 0,
                "candidate_id": node_id,
                "score": node.score,
                "metrics": node.results,
            },
        )
        
        self.logger.log_node(node, 0, database=self.database)
        self.mirror.mirror_round(node, 0, step_dir)

        self.best_snapshot.update_if_better(
            node,
            step_name="step_0_initial",
            source_step_dir=step_dir,
        )
        
        self.initial_node_created = True
    
    def _run_sequential(
        self,
        max_steps: int,
        task_description: Optional[str],
        eval_script: Optional[str],
        sample_n: int,
        target_score: Optional[float] = None,
        patience: Optional[int] = None,
    ):
        """Execute evolution steps one after another in the current process.

        Honors optional convergence controls (``target_score``/``patience``).
        With both ``None`` this is the original fixed-step loop.
        """
        convergence = target_score is not None or patience is not None
        if convergence:
            self.logger.info(
                f"Starting sequential pipeline for up to {max_steps} steps "
                f"(target_score={target_score}, patience={patience})"
            )
        else:
            self.logger.info(f"Starting sequential pipeline for {max_steps} steps")

        best = self.get_best_node()
        best_score = best.score if best else float("-inf")
        stale = 0

        for i in range(max_steps):
            node = self.run_step(
                task_description=task_description,
                eval_script=eval_script,
                sample_n=sample_n,
            )

            if node is None:
                self.logger.warning("Step failed, continuing to next step...")

            if not convergence:
                continue

            # Judge robustness: a step that produced no genuine judge score
            # (every council seat returned nothing, or the judge refused/failed
            # on all of them) must not corrupt the convergence signal. Counting
            # it as "no improvement" prematurely exhausts patience and maxes a
            # book out below its true ceiling. Skip it — the hard max_steps
            # ceiling still bounds the run.
            if node is None or node.meta_info.get("judge_failed_step"):
                self.logger.info(
                    f"Step {i + 1}/{max_steps} produced no scored candidate "
                    f"(upstream refusal / judge failure) — not counting toward "
                    f"patience; best={best_score:.4f}"
                )
                continue

            current = self.get_best_node()
            current_score = current.score if current else best_score
            if current_score > best_score + 1e-9:
                self.logger.info(
                    f"Best improved {best_score:.4f} -> {current_score:.4f} "
                    f"(step {i + 1}/{max_steps})"
                )
                best_score = current_score
                stale = 0
            else:
                stale += 1
                self.logger.info(
                    f"No improvement ({stale} consecutive); best={best_score:.4f}"
                )

            if target_score is not None and best_score >= target_score:
                self.logger.info(
                    f"Converged: best {best_score:.4f} >= target {target_score:.4f}. "
                    f"Stopping after {i + 1} step(s)."
                )
                break
            if patience is not None and stale >= patience:
                self.logger.info(
                    f"Maxed out: no improvement for {patience} step(s) "
                    f"(best {best_score:.4f}). Stopping after {i + 1} step(s)."
                )
                break

        self.logger.info("Pipeline completed")
        self.mirror.complete(self.database.get_all())
        self.logger.finish()
    
    def _run_parallel(
        self,
        max_steps: int,
        task_description: Optional[str],
        eval_script: Optional[str],
        sample_n: int,
    ):
        """Execute evolution steps across the configured worker pool."""
        self.logger.info(f"Starting parallel pipeline with {self.num_workers} workers for {max_steps} steps")
        
        completed_steps = 0
        failed_steps = 0
        
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = []
            for _ in range(max_steps):
                future = executor.submit(
                    self.run_step,
                    task_description=task_description,
                    eval_script=eval_script,
                    sample_n=sample_n,
                )
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    node = future.result()
                    if node is not None:
                        completed_steps += 1
                    else:
                        failed_steps += 1
                        self.logger.warning("Step failed, worker will continue with next task...")
                except Exception as e:
                    failed_steps += 1
                    self.logger.error(f"Worker encountered unexpected error: {type(e).__name__}: {e}")
                    self.logger.error(traceback.format_exc())
        
        self.logger.info(f"Parallel pipeline completed: {completed_steps} successful, {failed_steps} failed")
        self.mirror.complete(self.database.get_all())
        self.logger.finish()
    
    def get_best_node(self) -> Optional[Node]:
        nodes = self.database.get_all()
        if not nodes:
            return None
        return max(nodes, key=lambda n: n.score)
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "experiment_name": self.experiment_name,
            "total_steps": self.step,
            "total_nodes": len(self.database),
            "total_cognition": len(self.cognition),
            "manager_initialized": self.manager_initialized,
            "llm_stats": self.logger.get_stats(),
        }
