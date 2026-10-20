# Reports

Every report is built from the run and judged records in `results/` by `crbench report` (and, where noted, the
scripts in `scripts/`). Scores use the benchmark's `core` profile; repeats of a configuration are pooled, so a
three-pass score adds up the matches, misses and false positives of the three passes.

| Report | What it is |
| --- | --- |
| `full-r123/` | **The main report.** 52 configurations (19 models) on the 50 pull requests, three passes pooled. |
| `frontier-r123/` | Claude Fable 5.1 and GPT-6 Astra on the frontier set of 10 pull requests, three passes pooled. |
| `frontier-view-full-r123/` | Every configuration, those two included, on the same 10 pull requests: the only like-for-like view of all 58. |
| `products/vs-full-r123.json` | The 21 review tools of the benchmark's public leaderboard, judged by the same panel, ranked with the 52 configurations (`scripts/site_products.py`, `scripts/products_vs_models.py`). |
| `passes/` | The same reports for each pass alone (`full-r1`, `full-r2`, `full-r3` and their frontier counterparts), for how much a single run moves. |

## What a report directory holds

| File | Contents |
| --- | --- |
| `report.md` | one row per configuration (precision, recall, F1, F2, cost, tokens, time, judge agreement), then best levels, slices and judges |
| `configs.csv` | the same rows as a table |
| `per_judge.csv` | each judge's own score for each configuration |
| `slices.csv` | F-scores by language, repository and the benchmark's pull request labels |
| `recall_by_category.csv`, `recall_by_severity.csv` | recall by the golden comment's category and severity |
| `precision_by_model_category.csv` | precision by the category the model gave its finding |
| `meta.json` | the set, pull requests, repeats, models and profile the report was built with |
| `analysis.json` | (`full-r123` only) `scripts/analyze.py`: tie groups, Pareto frontier, effort comparisons, pass-to-pass stability, complementarity, judge agreement, operations |
| `blog_numbers.txt` | (`full-r123` only) every number in the write-up, from `scripts/blog_numbers.py` |

## Two kinds of interval

`report.md` gives each F2 a 95% interval that resamples (pull request, pass) pairs. `analysis.json` resamples pull
requests with their passes kept together, which is the honest unit when the same pull request is reviewed three
times; its intervals are wider, and its tie groups (a paired bootstrap, 4,000 draws) are the ones the write-up uses.

## Rebuilding

```bash
crbench report --set full --repeats 1-3 --frontier --name full-r123
crbench report --set frontier --repeats 1-3 --name frontier-r123
crbench export
python scripts/analyze.py full-r123 frontier-view-full-r123 1-3
python scripts/products_vs_models.py full-r123 1-3
python scripts/blog_numbers.py full-r123 1-3 > reports/full-r123/blog_numbers.txt
python scripts/verify_report.py full-r123
```
