# The dataset

`results/dataset/` holds everything the benchmark recorded as analysis-ready tables, one per entity, joined by ids
(`crbench export`, `crbench/export.py`). Any comparison can be made from them with a group-by: model, effort level,
route, pull request size, language, repository, the benchmark's pull request labels, golden severity and category, the
model's own severity and category, judge, cost, tokens or time.

## Ids

| Id | Form | Example |
| --- | --- | --- |
| `pr` | `<repository>__<number>` | `cal.com__10600` |
| `golden` | `<pr>#g<n>` | `cal.com__10600#g0` |
| `run` | `<model>__<tier>__r<repeat>@<pr>` | `claude-sonnet-5.5__low__r1@cal.com__10600` |
| `finding` | `<run>#f<n>` | `claude-sonnet-5.5__low__r1@cal.com__10600#f3` |

`tier` is the configured level: `low`, `default` or `xhigh`. For DeepSeek and GLM, `default` sends `high`; for Gemini,
`xhigh` sends `high`; Mistral's `low` is reasoning off (`models.csv` has the exact parameters).

## Tables

| File | One row per | Columns |
| --- | --- | --- |
| `models.csv` | model | `model`, `family`, `route`, `provider_model`, `provider_pin`, `sets`, `tier_low` / `tier_default` / `tier_xhigh` (the parameters each level sends), list prices per 1M tokens (`price_input`, `price_output`, `price_cache_read`, `price_cache_write`, `price_long_context`) |
| `prs.csv` | pull request | `pr`, `golden_url`, `in_full`, `in_frontier`, `repository`, `source_repo`, `language`, `title`, `changed_files`, `additions`, `deletions`, `size`, the benchmark's labels (`domain`, `change_type`, `complexity`, `difficulty`, `risk`, `context`, `concern`, `bug_categories`), golden counts by severity and profile, `benchmark_note` |
| `goldens.csv` | golden comment | `golden`, `pr`, `severity`, `category`, `in_strict`, `in_core`, `in_all`, `text` |
| `runs.csv` | review | `run`, `model`, `tier`, `pr`, `repeat`, `set`, `route`, `provider_served`, `served_model`, `status` (`ok` or `parse_error`), `finish_reason`, `calls`, tokens (`prompt_tokens`, `input`, `cache_read`, `cache_write`, `output`, `reasoning`), `cost_list`, `cost_uncached`, `cost_reported`, `latency_s`, `first_text_s`, `findings`, `salvaged`, `prompt_chars`, `prompt_sha`, `files_patch_only`, `params` |
| `calls.csv` | API call of a review (a retry is a second call) | `run`, `call`, timing (`latency_s`, `first_chunk_s`, `first_text_s`), `finish_reason`, tokens, `cost_list`, `cost_reported`, `response_id`, `provider_served`, `http_attempts`, `failed_attempts` |
| `findings.csv` | finding | `finding`, `run`, `model`, `tier`, `pr`, `repeat`, `file`, `line`, `model_severity`, `model_category`, `title`, `body`, `panel` (`matches_golden`, `false_positive` or `unresolved`), `matched_golden`, `judges_fp`, `dedup_group` |
| `golden_results.csv` | (review, golden comment) | `run`, `golden`, `found`, `judges_yes` (0 to 3), `yes_by`, `panel` (the three judges), `matched_finding`, `confidence` |
| `verdicts.csv` | (review, judge, golden or finding) | `run`, `judge`, `kind` (`golden_found`, `golden_missed`, `finding_false_positive`), `golden`, `finding`, `confidence`, `reasoning` (the judge's own words) |
| `judge_calls.csv.gz` | judge API call (600,000 rows, gzipped) | `ts`, `judge`, `step` (`step2` dedup, `step3` matching), `tool` (the reviewed configuration), `status`, `latency_s`, `cost_list`, `cost_reported`, tokens, `error` |

Every table covers the three passes; filter on `repeat` for one pass.

## Recomputing a score

F2 of a configuration on the `core` profile, three passes pooled, as the reports compute it:

```python
import pandas as pd

goldens = pd.read_csv("results/dataset/goldens.csv")
results = pd.read_csv("results/dataset/golden_results.csv")
findings = pd.read_csv("results/dataset/findings.csv")

core = set(goldens.loc[goldens.in_core, "golden"])
res = results[results.golden.isin(core)]

def f2(model, tier):
    r = res[(res.model == model) & (res.tier == tier)]
    tp, fn = int(r.found.sum()), int((~r.found).sum())
    fp = int(((findings.model == model) & (findings.tier == tier) & (findings.panel == "false_positive")).sum())
    p, rec = tp / (tp + fp), tp / (tp + fn)
    return 5 * p * rec / (4 * p + rec)

print(round(100 * f2("claude-sonnet-5.5", "low"), 1))   # 64.4
```

The same pattern gives any slice: join `results` with `prs` for language or size, with `goldens` for severity or
category, or keep only `judges_yes == 3` for unanimous matches. `scripts/analyze.py` does this for everything in the
write-up.

## The raw records

The tables are flattened from the records under `results/`:

- `results/runs/<model>/<tier>/<pr>__r<n>.json`: one review, with the model's raw reply (`response_text`), its parsed
  findings, every call with the provider's raw usage object, and the prompt's hash and parameters.
- `results/judged/<model>__<tier>__r<n>.json`: one configuration's judging, with each judge's rows per pull request
  (`per_judge`), the vote (`voted`) and the duplicate groups (`dedup_groups`).
- `results/products/`, `results/calibration/`, `results/control/` hold the same kinds of records for the review tools,
  the judge calibration and the prompt control, with their judge-call logs (`judge_usage/*.jsonl`).
