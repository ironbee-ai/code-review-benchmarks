# code-review-benchmarks

How well does a raw LLM review a pull request, with no product around it? This repository runs 21 models, at up to
three effort levels each, on the offline set of [Martian's Code Review Bench](https://github.com/withmartian/code-review-benchmark):
50 real pull requests from Sentry, Grafana, Keycloak, Cal.com and Discourse, with 173 human-checked golden comments.
Every model gets the same prompt and the same pull request content in one call, its findings are scored by the
benchmark's own dedup and matching steps, and a panel of three judges from other model families decides each match.
Every review ran three times.

The write-up: [The Honest Raw LLM Code Review Benchmark](https://ironbee.ai/blog/the-honest-raw-llm-code-review-benchmark).
Everything behind it is here: the harness, the prompts, every model reply, every judge verdict, every cost, and the
scripts that produce each number and figure.

## Results

Each model at its best effort level, on the 50 pull requests, three passes averaged (`reports/full-r123`). Groups come
from a paired bootstrap over pull requests: a configuration stays in a group unless the group's leader is
significantly better, so the order inside a group is not significant.

| Model | Level | Group | Precision | Recall | F1 | F2 | $ per PR | Median time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | low | 1 | 46.0 | 71.5 | 56.0 | **64.4** | 0.142 | 9 s |
| Claude Opus 5.5 | low | 1 | 46.3 | 67.9 | 55.1 | **62.1** | 0.283 | 11 s |
| Claude Opus 5 | low | 1 | 38.3 | 73.2 | 50.3 | **61.9** | 0.449 | 32 s |
| Grok 4.7 | low | 1 | 46.8 | 67.3 | 55.2 | **61.9** | 0.139 | 92 s |
| Muse Spark 1.3 | default | 1 | 42.4 | 68.4 | 52.3 | **60.9** | 0.072 | 59 s |
| Muse Wonder | low | 2 | 43.0 | 61.8 | 50.7 | **56.8** | 0.214 | 29 s |
| Gemini 4 Argon | high | 2 | 50.9 | 58.2 | 54.3 | **56.6** | 0.235 | 2.2 min |
| DeepSeek V4.1 Flash | high | 2 | 37.3 | 64.8 | 47.3 | **56.5** | 0.025 | 2.2 min |
| Kimi K3 | xhigh | 2 | 38.7 | 62.4 | 47.8 | **55.6** | 0.253 | 4.4 min |
| GLM 5.3 | high | 2 | 34.4 | 65.2 | 45.0 | **55.3** | 0.102 | 1.9 min |
| Qwen 3.8 Max | default | 2 | 29.1 | 69.4 | 41.0 | **54.4** | 0.214 | 8.5 min |
| DeepSeek V4 Pro | high | 3 | 40.0 | 56.8 | 46.9 | **52.4** | 0.156 | 4.1 min |
| Claude Haiku 5.5 | default | 3 | 27.9 | 63.7 | 38.8 | **50.7** | 0.023 | 23 s |
| Claude Sonnet 5 | xhigh | 4 | 29.7 | 59.3 | 39.6 | **49.5** | 0.401 | 4.4 min |
| GPT-5.6 Terra | xhigh | 4 | 39.8 | 51.9 | 45.1 | **48.9** | 0.212 | 2.0 min |
| GPT-6.1 Sol | xhigh | 4 | 38.5 | 50.4 | 43.7 | **47.5** | 0.150 | 1.7 min |
| MiniMax M3 | default | 4 | 28.6 | 55.9 | 37.9 | **47.0** | 0.037 | 94 s |
| GPT-6 Luna | xhigh | 5 | 43.0 | 44.5 | 43.7 | **44.2** | 0.009 | 68 s |
| Mistral Large 4 | no reasoning | 6 | 10.7 | 73.2 | 18.7 | **33.8** | 0.054 | 50 s |

Every configuration (52 on the 50 pull requests, 58 with the frontier set) is in `reports/full-r123/report.md` and
`configs.csv`. Claude Fable 5.1 and GPT-6 Astra ran on a fixed subset of 10 pull requests (`reports/frontier-r123`).
The 21 review tools of the benchmark's public leaderboard, judged by the same panel, are ranked with the models in
`reports/products/vs-full-r123.json`. `reports/README.md` says what each report holds.

## Documentation

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md): the procedure in full, from the prompt to the tie groups
- [docs/DATASET.md](docs/DATASET.md): the tables in `results/dataset/`, their columns, and how to recompute a score
- [docs/LESSONS.md](docs/LESSONS.md): what went wrong, or nearly did, and what the harness does about it
- [docs/EXTENDING.md](docs/EXTENDING.md): adding a model, another prompt or another judge
- [reports/README.md](reports/README.md): what each report holds

## How a run works

| Step | What happens | Where |
| --- | --- | --- |
| data | the benchmark cloned at a pinned commit (`data/martian/COMMIT`); per pull request a snapshot of the benchmark's fork of it: title, description, every changed file's diff and full content at the head | `work/martian`, `data/prs/`, `data/sets/` |
| review | one call per (model, level, pull request, repeat): system prompt plus the pull request; the model answers with a JSON list of findings | `results/runs/<model>/<tier>/<pr>__r<n>.json` |
| judge | each finding becomes one candidate in the benchmark's format; the benchmark's `step2_5_dedup_candidates` and `step3_judge_comments` run unmodified in private copies of the benchmark, three judges per model | `results/judged/<model>__<tier>__r<n>.json` |
| vote | a golden comment is found when two of the three judges match it; a finding is a false positive when two of three leave it unmatched | `crbench/vote.py` |
| report | precision, recall, F1 and F2 on the benchmark's profiles; cost, tokens and time; slices by language, repository, PR labels, golden category and severity; judge agreement | `reports/` |

**One harness for every model.** One system prompt (`configs/prompts/review_system.md`), one user template, no tools,
no per-model tuning. A changed file is shown in full, with numbered lines, and with its diff; a file over 60,000
characters, and the largest files once a prompt holds 500,000 characters of file content, are shown as their diff
only. The prompt names the issue types the benchmark's core profile counts; `configs/prompts/review_system_neutral.md`
is the neutral prompt of the control run (`scripts/control_prompt.py`).

**Effort levels.** `low`, `default` (no effort parameter: the vendor's default) and `xhigh`, the highest level below
`max`. Nothing ever sends `max`. Where a vendor's default or `xhigh` is its maximum (GLM 5.3, DeepSeek), the model ran
`low` and `high`. Mistral Large 4 ran with reasoning off. The exact parameters per model are in `configs/models.yaml`.

**Judges.** The pool is in `configs/judges.yaml`, in order: Gemini 4 Argon, GPT-6.1 Sol, Claude Opus 5.5, Grok 4.7. A
model is judged by the first three judges outside its own family (Claude models by Gemini, Sol and Grok), each with
the benchmark's own judge prompt, at low reasoning effort; the three vote. Judge calls go through a local proxy
(`crbench/judge_proxy.py`) that sends each on the judge's route and logs its usage and cost; the benchmark's code never
sees a key. A model's duplicate groups are made by its first judge and given to the other two.

**Cost.** Every call's usage is recorded as the provider returns it, with the raw usage object. Reports price each
call from `configs/pricing.yaml` at the standard on-demand rate of the route, with long-context rates where a prompt
crosses a model's threshold. The "uncached" figure prices every input token at the input rate, since caching differs
by provider; it is the one the write-up uses. `scripts/verify_report.py` recomputes a report's scores with the
benchmark's own scorer and its costs from the run files.

## Models and routes

| Route | Models | Key |
| --- | --- | --- |
| `bedrock-anthropic` (Messages API on Amazon Bedrock) | Claude Opus 5.5, Sonnet 5.5, Haiku 5.5, Opus 5, Sonnet 5, Fable 5.1 | `AWS_BEARER_TOKEN_BEDROCK` |
| `bedrock-openai` (Bedrock's OpenAI-compatible endpoint) | GPT-6.1 Sol, GPT-5.6 Terra, GPT-6 Luna, GPT-6 Astra, Kimi K3 | `AWS_BEARER_TOKEN_BEDROCK` |
| `openrouter` (provider pinned, no fallback) | Muse Spark 1.3 and Muse Wonder (Meta), DeepSeek V4 Pro and V4.1 Flash (DeepSeek), Qwen 3.8 Max (Alibaba), GLM 5.3 (Z.AI), MiniMax M3 (MiniMax), Gemini 4 Argon (Google AI Studio), Mistral Large 4 (Mistral), Grok 4.7 (xAI) | `OPENROUTER_API_KEY` |

Keys are read from the environment, from `.env`, or from the file `CRBENCH_ENV_FILE` points to (see `.env.example`).
Nothing in `configs/` holds a secret.

## Data

| Path | What it holds |
| --- | --- |
| `results/dataset/` | the analysis-ready tables (`crbench export`), one per entity, joined by ids: `models.csv`, `prs.csv`, `goldens.csv`, `runs.csv` (a row per review), `calls.csv` (a row per API call), `findings.csv` (a row per finding, with the panel's verdict), `golden_results.csv` (a row per review and golden comment), `verdicts.csv` (each judge's own verdict, confidence and reasoning), `judge_calls.csv.gz` (a row per judge API call: tokens, cost, time, status) |
| `results/runs/` | every review: the model's raw reply, its parsed findings, usage, cost, timing and the provider that served it (7,980 files) |
| `results/judged/` | every configuration's judged record: each judge's rows per pull request, the vote, the duplicate groups |
| `results/products/` | the 21 leaderboard tools judged by the same panel (`scripts/site_products.py`); Gitar's reviews collected from GitHub |
| `results/calibration/` | the panel against the benchmark's own GPT-5.2 judge on the same tool findings (`scripts/calibrate.py`) |
| `results/control/` | the neutral-prompt control run (`scripts/control_prompt.py`) |
| `results/fp_audit/` | 48 "false positives" checked against the code |
| `data/martian/` | the benchmark's golden comments, pull request labels, and its site's leaderboard and timing data (2026-09-08) |
| `data/sets/` | the full set (50 pull requests) and the frontier set (10) |

The pull request snapshots (`data/prs/`) and the benchmark checkout (`work/`) are rebuilt by `crbench data`.

## Running it

```bash
uv venv && uv pip install -e '.[dev,charts]'
cp .env.example .env                           # then fill in the keys
crbench data                                   # clone the benchmark, snapshot the PRs, pick the frontier subset
crbench probe --judges                         # one tiny call per (model, level) and per judge
crbench estimate --set full                    # prompt sizes, projected cost of one pass
crbench run --set full --prs sentry__93824     # a trial on one pull request
crbench judge --set full --prs sentry__93824
crbench run --set full --repeats 1-3           # resumable; a run made with another prompt or parameters is redone
crbench run --set frontier --repeats 1-3
crbench judge --set full --repeats 1-3 && crbench judge --set frontier --repeats 1-3
crbench check --set full --repeats 1-3         # every configuration ran, is current, judged and complete
crbench report --set full --repeats 1-3 --frontier --name full-r123
crbench report --set frontier --repeats 1-3 --name frontier-r123
python scripts/verify_report.py full-r123      # re-scores the report with the benchmark's own scorer; 0 problems expected
crbench export                                 # results/dataset/
python scripts/analyze.py full-r123 frontier-view-full-r123 1-3      # groups, effort, stability, judges: analysis.json
python scripts/products_vs_models.py full-r123 1-3                   # the leaderboard tools and the models in one ranking
python scripts/blog_numbers.py full-r123 1-3                         # every number in the write-up
python scripts/blog_figures.py <out dir> full-r123                   # every figure in the write-up
```

Ctrl-C stops a run or a judging pass cleanly; the same command resumes. `scripts/pass.sh` runs a whole pass
unattended. At list price, one pass of the first 43 configurations (2,060 reviews) cost about $350 for the reviews and
$280 to $330 for the judging.

## Known limits

- The pull requests and their goldens are public: models may have seen them in training.
- The judges are LLMs. The reports show each judge's own score, the judges' agreement (Fleiss' kappa) and the share
  of goldens they split on; `results/calibration/` compares the panel with the benchmark's own judge.
- The golden list does not hold every real issue, so precision is a lower bound (`results/fp_audit/`).
- Five pull requests carry the benchmark's own note that the reviewed commit is not in the repository or that the pull
  request is assembled from several; they stay in the set as the benchmark scores them.

## License

MIT, see `LICENSE`. The benchmark's data in `data/martian/` comes from
[Martian's Code Review Bench](https://github.com/withmartian/code-review-benchmark) (MIT). The pull requests belong to
their projects and stay under those projects' licenses.
