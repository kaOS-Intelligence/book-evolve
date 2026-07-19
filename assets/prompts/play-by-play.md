# Book Evolution — Play-by-Play Progress

This template governs how I communicate progress during chapter evolution.
I report at each evolution step so the author always knows where we are.

---

## Per-Chapter Flow

### Step 0: Seed & Provision

```
SEEDING cognition store for Chapter {N}.
  → Dictation: {word_count} words loaded.
  → Reference books: {count} sources loaded.
  → Building bge-m3 FAISS index... done.

PROVISIONING experiment directory: book_evolution_chapter_{NN}.
  → Symlinked shared assets (evaluator, cognition store).
  → Copied chapter-specific config and prompts.
  → Ready.
```

### Each Evolution Step

```
STEP {current}/{max_steps}  |  Best score: {best_score:.4f}  |  Target: {target_score}

  Council generating {council_size} candidates...
  → Seat 1 ({COUNCIL_MODEL_1}): done.
  → Seat 2 ({COUNCIL_MODEL_2}): done.
  → Seat 3 ({COUNCIL_MODEL_3}): done.

  Judge scoring candidates on 6 axes...
  → Candidate A: {score_a:.4f}
  → Candidate B: {score_b:.4f}
  → Candidate C: {score_c:.4f}
  → Best this step: {best_step_name} ({best_step_score:.4f})

  Axis breakdown for best candidate:
    Content Fidelity:     {content_fidelity:.2f}
    Author Style Match:   {author_style_match:.2f}
    Literary Quality:     {literary_quality:.2f}
    Structural Coherence: {structural_coherence:.2f}
    Readability:          {readability:.2f}
    Evolutionary Novelty: {evolutionary_novelty:.2f}

  Analyzer lesson: {lesson_summary}
```

### Convergence

```
CONVERGED at step {step} with score {score:.4f} (target: {target_score}).

  Total steps: {total_steps}
  Total time:   {elapsed_time}
  Best chapter score: {best_score:.4f}

  Promoting to output/chapters/{chapter_slug}.mdx...
  → toc.json updated.
  → index.mdx regenerated.

  Chapter {N} complete. On to Chapter {N+1}.
```

### Plateau (no convergence)

```
MAXED OUT at step {max_steps} with best score {best_score:.4f}.

  The chapter did not reach the target score of {target_score}
  after {max_steps} steps. The last {patience} steps showed no
  improvement.

  RECOMMENDATION:
  [ ] Accept the best candidate ({best_score:.4f}) and move on.
  [ ] Revise the dictation for this chapter and re-evolve.
  [ ] Add more reference material to strengthen the style anchor.
  [ ] Lower the target score for this chapter.

  What would you like to do?
```

## Multi-Chapter Summary

After all chapters are complete, provide a summary:

```
=== BOOK EVOLUTION COMPLETE ===

  Title: {book_title}
  Chapters evolved: {completed_count}/{total_count}
  Average score: {average_score:.4f}

  Chapter scores:
    Chapter  1: {score_1:.4f}  [{steps} steps]
    Chapter  2: {score_2:.4f}  [{steps} steps]
    Chapter  3: {score_3:.4f}  [{steps} steps]  (plateaued at step {max})
    ...

  Total evolution time: {total_time}
  Output: output/chapters/

  Next steps:
  1. Review each chapter in output/chapters/.
  2. Edit or request re-evolution for any chapter.
  3. Add introduction: write 00-introduction.mdx.
  4. Generate cover art.
  5. Your book is ready for publishing.

  Thank you for the collaboration. This was a pleasure.
```

## Error Handling

```
ERROR in Chapter {N}, Step {S}:

  {error_message}

  The pipeline handles this gracefully:
  → Retrying... (attempt {attempt}/{max_retries})
  → If retries fail, the chapter preserves its best candidate.
  → You can resume from the last checkpoint with:
    npx @kaos-intelligence/book-evolve evolve --chapter {N}

  Status: {status}
```

## Test Run

```
TEST RUN — Chapter 1, first 500 words

  This is a quick validation of style match before full evolution.

  Seed → Evolve (1 step) → Score.

  Result: {score:.4f} on 500-word sample.

  Axis breakdown:
    Content Fidelity:     {cf:.2f}
    Author Style Match:   {asm:.2f}
    Literary Quality:     {lq:.2f}

  RECOMMENDATION:
  [ ] Style match looks good — proceed with full Chapter 1.
  [ ] Style match needs work — add more reference material or
      adjust the dictation before proceeding.
  [ ] Let me see the sample output first.
```
