# Methodology

What exactly was measured, and how. The write-up tells the results; this file is the procedure, with pointers to the
code that implements each step.

## The benchmark

The offline set of [Martian's Code Review Bench](https://github.com/withmartian/code-review-benchmark), pinned to the
commit in `data/martian/COMMIT`: 50 pull requests, ten each from Sentry (Python), Grafana (Go), Keycloak (Java),
Cal.com (TypeScript) and Discourse (Ruby), each a fork of a real pull request. Each comes with golden comments, the
issues a careful reviewer should raise: 173 in all, with a severity (critical, high, medium, low) and a category.

The benchmark's profiles decide which goldens count (`crbench/metrics.py`, `PROFILES`):

| Profile | Categories | Goldens |
| --- | --- | --- |
| `strict` | bug, security, concurrency, data, api | |
| `core` (the default, and the one every score here uses) | strict + perf, test_gap, doc_defect | 158 |
| `all` | core + style, speculative | 173 |

**Sets** (`data/sets/`). `full` is the fifty. `frontier` is ten of them, two per repository, for the two most expensive
models (Claude Fable 5.1, GPT-6 Astra): per repository, the pull request whose golden count is nearest the
repository's median, then the one farthest from it in size; pull requests the benchmark itself flags (a reviewed
commit missing from the repository, a pull request assembled from several) are never chosen (`crbench/dataset.py`,
`make_subset`). Every model also runs the frontier ten as part of the full set, so all 58 configurations can be
compared there (`reports/frontier-view-full-r123`).

## The review call

One call per (model, effort level, pull request, repeat), with no tools and no repository access
(`crbench/prompt.py`, `crbench/runner.py`).

- **System prompt**: `configs/prompts/review_system.md`, the same for every model. It asks for a JSON list of findings,
  each with a file, a line, a severity, a category and a self-contained explanation; it names the issue types the
  `core` profile counts and asks the model to leave out style and speculation.
- **User message**: `configs/prompts/review_user.md` filled with the pull request: title, description, a table of the
  changed files, and per changed file its full content at the head, with line numbers, and its unified diff.
- **Prompt budget** (`configs/runs.yaml`): a file over 60,000 characters is shown as its diff only; once the files'
  full contents pass 500,000 characters in total, the largest files drop to diff only first; a diff over 40,000
  characters is cut with a marker. The median prompt is about 30,000 tokens.
- **Limits**: 65,536 output tokens per call, thinking included; 60 minutes per attempt.
- **Retries**: an API error is retried within the call. A reply that is not the JSON asked for, or that is cut at the
  output cap, is asked again, at most twice (`parse_retries`); `scripts/one_more_attempt.py` gives a run that is still
  without a usable reply up to four more calls. A reply that finished but carries broken JSON keeps every complete
  finding it wrote (`salvage_findings`); a reply cut at the cap is an unfinished review and counts as empty.
- **Provenance**: every run records the prompt's hash and size, the parameters sent, the route, the provider that
  served it, the usage object as the provider returned it, timings and every attempt (`results/runs/`). A run made
  with another prompt, other parameters or another provider pin is redone, never mixed in.

## Effort levels

Three levels per model, mapped to each vendor's own parameter in `configs/models.yaml`:

- `low`: the vendor's low setting.
- `default`: no effort parameter at all, the vendor's default.
- `xhigh`: the highest level below `max`. Nothing ever sends `max`.

Where a vendor's default or highest level is its maximum (GLM 5.3; DeepSeek V4 Pro and V4.1 Flash), the model ran
`low` and `high`, and the reports name the level actually sent. Mistral Large 4 ran with reasoning off only: with
reasoning on it spent its whole output budget thinking on every real pull request tried. Muse Spark 1.3 and Muse
Wonder were probed to confirm that their default is not their highest level.

## Judging

The benchmark's own steps, unmodified apart from one time limit, run in private copies of the benchmark called lanes
(`crbench/lane.py`, `crbench/judge.py`):

1. **Dedup** (`step2_5_dedup_candidates`): one call per review groups duplicate findings. It runs with the first judge
   of the review's panel, and its groups are given to the other two, so all three judges score the same groups.
2. **Matching** (`step3_judge_comments`): for every golden comment, the judge decides whether one of the review's
   findings describes the same issue. Each call gets 30 seconds, as in the benchmark. A review gets 90 minutes in
   total instead of the benchmark's 30, because one review with 538 findings needed 36 minutes of the slowest judge;
   a review that finishes within 30 minutes gets the same verdicts either way.

**The panel** (`configs/judges.yaml`). The pool, in order, is Gemini 4 Argon, GPT-6.1 Sol, Claude Opus 5.5, Grok 4.7. A
model is judged by the first three judges outside its own family: Claude models by Gemini, Sol and Grok; GPT models by
Gemini, Opus and Grok; everything else by Gemini, Sol and Opus. The judges run at low reasoning effort (the
benchmark's own judges do not reason).

**The proxy** (`crbench/judge_proxy.py`). The benchmark's steps talk to a local endpoint that forwards each call on the
judge's route with the judge's parameters, logs its usage and cost, and never shows the steps a key. Two judge-reply
quirks are handled there, never changing a verdict: a reply that explains itself before its JSON is read from its
last JSON object, and a verdict whose `match` or `confidence` is written as a string is retyped (a `"false"` string
would otherwise count as a match).

**The vote** (`crbench/vote.py`). A golden comment is found when at least two of the three judges matched it. A finding
is a false positive when at least two judges left it unmatched; a finding the judges split on is `unresolved` and
counts neither way (1.3% of findings). A pull request missing a judge's verdict is reported as incomplete and left out
of the counts; there are none in the published results.

## Scores

Per configuration, with repeats pooled: TP = core goldens found, FN = core goldens not found, FP = findings voted false
positive. Precision = TP / (TP + FP), recall = TP / (TP + FN), F1, and F2 (beta = 2, recall weighted four times as much
as precision), the benchmark's default. Pooling three passes adds up their counts; recall is then exactly the mean of
the passes, and precision and F2 come within 0.15 points of it.

**Intervals and groups** (`scripts/analyze.py`). A paired bootstrap over pull requests, 4,000 draws, seed 7: each draw
resamples the 50 pull requests with their three passes kept together, the same draw for every configuration. A
configuration stays in its group unless the group's leader is better in at least 97.5% of draws; inside a group, the
order is not significant. `report.md` also prints a narrower interval that resamples (pull request, pass) pairs; the
write-up uses the analysis.

**Stability.** Each configuration's F2 per pass, the span between its lowest and highest pass, and a paired bootstrap of
each pair of passes.

**Cost** (`configs/pricing.yaml`, `crbench/metrics.py`). The list price of the tokens each call used: the standard
on-demand rate on the route called (Bedrock: global cross-Region inference), long-context rates where a prompt crosses
a model's threshold, no off-peak, batch or flex discount. "Uncached" prices every input token at the input rate, since
implicit caching differs by provider; the write-up uses it. The cost OpenRouter reports is kept beside it.

**Time.** The wall-clock time of the review call, retries included. Tables give the median over pull requests, the
speed charts the mean.

## The review tools

The 21 tools of the benchmark site's offline leaderboard (as of 2026-09-08) were judged by the same panel
(`scripts/site_products.py`). The benchmark turns each tool's review comments into findings with its default judge,
Claude Opus 4.5; for 20 tools those published findings were used. Gitar's reviews are on GitHub but not yet in the
benchmark's repository, so they were collected with the benchmark's own code and turned into findings with Claude
Opus 4.5 and the benchmark's extraction prompt (`results/products/gitar-v2/`). No tool was judged by its own family:
Grok 4.7 stood in for Claude Opus 5.5 on Claude Code, and for Gemini 4 Argon on Gemini. A tool's reviews do not change,
so each was judged once. `scripts/products_vs_models.py` ranks the tools and the 52 configurations together, with the
same bootstrap.

## Checks on the judge

- **Calibration** (`scripts/calibrate.py`, `results/calibration/`): the findings the benchmark's GPT-5.2 judge extracted
  for three tools, judged by our panel; F2 within one point of the benchmark's own verdicts.
- **Agreement**: Fleiss' kappa per configuration, each judge's own score (`per_judge.csv`), the share of goldens found
  unanimously, and the ranking under each judge alone (`analysis.json`, `judges`).
- **False-positive audit** (`results/fp_audit/`): 48 findings the panel called false positives, from six
  configurations of the first pass, checked against the code by reviewers who did not see which model wrote them.
- **Prompt control** (`scripts/control_prompt.py`, `results/control/`): the four best configurations of the first pass
  run once more with a neutral prompt, `configs/prompts/review_system_neutral.md` (no list of issue types, no
  exclusions, no category field).
- **Independent re-scoring** (`scripts/verify_report.py`): every report is re-voted from the judges' raw rows, scored
  with the benchmark's own `score_profiles.py`, and its costs recomputed from the run files.
