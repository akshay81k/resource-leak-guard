# Implementation Plan: Static Resource-Leak Guard for CI/CD

## Project brief

Build a CLI tool + GitHub Action that statically analyzes source code to detect
unclosed resources (file handles, DB connections, sockets), fails CI builds when
found, and auto-generates patch suggestions that wrap the leak in the language's
safe-resource idiom (try-with-resources, `defer`, `with`, `using`).

**Scope for v1: Java only.** Get the full pipeline working end-to-end on one
language before generalizing. Architecture must support adding a second language
(Go) via config, not code changes, as a stretch goal.

**Non-goals for v1:** interprocedural analysis (resource passed to another
function), resources stored in struct/class fields, multi-file dataflow.
These should be explicitly flagged as "low confidence" or skipped, not silently
mishandled.

---

## Repo structure to create

```
resource-leak-guard/
├── src/
│   ├── parser/
│   │   ├── ast_loader.py          # tree-sitter setup + parsing
│   │   └── cfg_builder.py         # AST -> control-flow graph
│   ├── rules/
│   │   ├── java.yaml              # acquisition/release/safe-wrapper patterns
│   │   └── schema.py              # rule-file validation
│   ├── analysis/
│   │   ├── resource_tracker.py    # per-function open/close state tracking
│   │   └── leak_detector.py       # path reachability check, confidence scoring
│   ├── patch/
│   │   ├── java_rewriter.py       # AST rewrite -> try-with-resources
│   │   └── diff_writer.py         # unified diff / patch file output
│   ├── cli.py                     # entrypoint: scan a path, print/report results
│   └── models.py                  # shared dataclasses (Finding, ResourceHandle, etc.)
├── tests/
│   ├── fixtures/java/             # sample .java files, one per test case (see Phase 2)
│   ├── test_cfg_builder.py
│   ├── test_leak_detector.py
│   └── test_patch_generation.py
├── .github/
│   ├── workflows/
│   │   └── self_check.yml         # runs the tool on this repo's own code
│   └── actions/
│       └── resource-leak-guard/
│           ├── action.yml
│           └── entrypoint.sh
├── hooks/
│   └── pre-commit-hook.sh         # standalone hook for local use
├── docs/
│   └── rule-file-format.md
├── requirements.txt
└── README.md
```

---

## Phase 1 — Parsing + CFG foundation

**Goal:** for a single Java method with no branching, produce a CFG with correct
basic blocks and identify one acquisition site.

Tasks:
1. Install `tree-sitter` + `tree-sitter-java` grammar. Write `ast_loader.py`:
   parse a `.java` file, return the tree + a helper to find all method
   declarations.
2. Define `models.py` dataclasses: `ResourceHandle` (var name, acquisition
   node, type), `BasicBlock` (statements, successors), `CFG` (blocks, entry,
   exit set), `Finding` (file, line, resource, confidence, message).
3. Write `cfg_builder.py`: walk a method body's AST and build a linear CFG
   first (no branches) — sequential statements as one basic block, single
   exit edge at the end/return.
4. Write `resource_tracker.py`: given a CFG + a rule file, find acquisition
   calls (match against `rules/java.yaml` patterns) and mark the resource
   variable's state as OPEN starting at that node.

**Acceptance test:** feed a 5-line Java method that opens a `FileInputStream`
and never closes it. Tool should identify one `ResourceHandle` and correctly
locate its acquisition line/column.

---

## Phase 2 — Branching, exceptions, and real leak detection

**Goal:** handle the actual hard part — multiple paths through a function.

Tasks:
1. Extend `cfg_builder.py` to handle: `if`/`else`, `for`/`while`, `try`/
   `catch`/`finally`, early `return`, and exception edges (any statement that
   can throw gets an edge to the enclosing `catch` or the function exit).
2. Extend `resource_tracker.py` to propagate OPEN/CLOSED state along every
   CFG edge (standard forward dataflow analysis — a simple worklist algorithm
   is enough, no need for a fixpoint framework).
3. Write `leak_detector.py`: a resource is "safe" only if **every** exit
   path (normal return, exception, end-of-function) passes through a `close()`
   call on that variable, OR the acquisition is inside a
   `try (Resource r = ...)` block (detect this from the AST node type
   directly, don't rely on tracking `.close()` since it's implicit).
4. Add confidence scoring: `definite` (all paths traced, resource type is a
   known closeable, no reassignment) vs `possible` (resource is reassigned
   conditionally, or passed as an argument to another method — these should
   warn, not fail the build).
5. Build the fixture set in `tests/fixtures/java/`, one file per case:
   - `01_no_leak_explicit_close.java`
   - `02_leak_missing_close.java`
   - `03_no_leak_try_with_resources.java`
   - `04_leak_only_on_exception_path.java` (closes on happy path, not on throw)
   - `05_no_leak_finally_block.java`
   - `06_possible_leak_conditional_reassignment.java`
   - `07_possible_leak_passed_to_helper.java`

**Acceptance test:** all 7 fixtures produce the expected `Finding` list
(including zero findings for the "no leak" cases) with correct confidence
levels.

---

## Phase 3 — Patch generation

**Goal:** for a `definite` leak, emit a unified diff that fixes it.

Tasks:
1. Write `java_rewriter.py`: given a `Finding` pointing at a leaked
   acquisition, use tree-sitter's edit API to rewrite the statement into a
   `try (Type var = acquisition) { ...original body... }` block. Handle the
   two common shapes: (a) resource used only within the rest of the current
   block — wrap the whole remainder; (b) resource used until an explicit
   (now-redundant) `close()` call — wrap up to and including that call, then
   delete the now-dead `close()` line.
2. Write `diff_writer.py`: produce a standard unified diff string
   (`git apply`-compatible) from the original source and the rewritten
   source.
3. Add a fallback path stub in `patch/` for cases the template can't handle
   (e.g. resource stored in a field) — for v1 this can just emit "manual fix
   required" with an explanation instead of a diff. Note this as the
   integration point for an LLM-assisted fallback (v2/stretch).

**Acceptance test:** run patch generation on fixture `02_leak_missing_close.java`,
apply the resulting diff with `git apply --check`, confirm it applies cleanly
and the resulting file passes the Phase 2 leak detector with zero findings.

---

## Phase 4 — CLI + CI integration

**Goal:** a working `pre-commit` hook and GitHub Action that fail builds and
post suggestions.

Tasks:
1. `cli.py`: `resource-leak-guard scan <path> [--diff-only] [--format=json|text]`.
   `--diff-only` restricts scanning to files changed vs a base ref (use for
   pre-commit speed). Exit code 1 if any `definite` finding exists.
2. `hooks/pre-commit-hook.sh`: runs `cli.py scan --diff-only` against staged
   files, prints findings + suggested patch inline, blocks the commit on
   `definite` findings.
3. `.github/actions/resource-leak-guard/action.yml`: composite or Docker
   action. Inputs: `fail-on` (definite|possible), `language`. Runs the CLI
   against the PR diff.
4. `entrypoint.sh` / a small script using `actions/github-script` (or direct
   REST calls) to post PR review comments using GitHub's `suggestion` code
   block syntax so the fix is one-click-appliable in the PR UI.
5. `.github/workflows/self_check.yml`: runs the action against this repo's
   own `tests/fixtures` on every push, as a living demo and regression test.

**Acceptance test:** open a test PR against a scratch repo containing
`02_leak_missing_close.java`. Action run should fail, and the PR should show
an inline suggestion comment that applies cleanly.

---

## Phase 5 — Stretch goals (only if Phases 1–4 are solid)

Priority order:
1. **Go support**: add `rules/go.yaml`, extend `cfg_builder.py`'s
   language-dispatch, add a `go_rewriter.py` that inserts `defer x.Close()`
   after the acquisition + error check. This is the single best "we
   generalized the architecture" demo point — do this before anything else
   in this phase.
2. **LLM-assisted fallback patching**: for `possible` findings or patterns
   the template rewriter rejects, call the Claude API with the function body
   + finding, ask for a minimal diff, validate it applies and re-passes the
   detector before showing it.
3. **Summary dashboard / metrics**: a small static HTML report (findings by
   file, confidence, historical trend if run against repo history) — mainly
   for the demo, not core functionality.
4. **Historical validation**: run the tool against a real OSS repo's git
   history, check how many of its findings correspond to commits that later
   manually fixed a leak. Good for a credibility slide.

---

## Definition of done for hackathon demo

- [ ] `resource-leak-guard scan` correctly classifies all 7 Phase 2 fixtures
- [ ] Patch generation produces a clean, applicable diff for the missing-close case
- [ ] GitHub Action fails a real PR and posts a one-click-appliable suggestion
- [ ] README documents the rule-file format and how to add a new language
- [ ] (Stretch) Go support proven on at least 2 fixtures
- [ ] Live demo script prepared: commit leak → push → red X → inline suggestion → apply → push → green check

## Key engineering risks to flag early

- **tree-sitter grammar quirks**: verify try-with-resources and lambda-captured
  resources parse into the node shapes you expect *before* building the CFG
  logic around them — spend 30 minutes exploring the AST in a REPL first.
- **False positives will kill the demo's credibility** — bias the `definite`
  classifier toward precision; anything ambiguous should degrade to `possible`
  (warn only) rather than fail the build.
- **Diff application must be exact** — off-by-one line/byte offsets from AST
  edits are the most likely source of "patch doesn't apply" bugs; test this
  path early and often, not last.
