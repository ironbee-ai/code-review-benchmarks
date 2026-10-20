# Extending it

## Add a model

1. **Describe it** in `configs/models.yaml`:

   ```yaml
   - id: my-model                   # the name used everywhere (results, reports, dataset)
     family: example               # judges of the same family never judge it
     route: openrouter             # bedrock-anthropic | bedrock-openai | openrouter
     model: example/my-model       # the provider's model id
     provider: { order: [example], allow_fallbacks: false }   # OpenRouter only: pin one provider
     tiers: { low: { reasoning: { effort: low } }, default: {}, xhigh: { reasoning: { effort: xhigh } } }
     sets: [full]                  # full, frontier, or both
   ```

   `default: {}` sends no effort parameter. A level that is the same configuration as another is written
   `{ same_as: default }` and not run twice. Never map a level to `max`.

2. **Price it** in `configs/pricing.yaml`: input, output, cache read and cache write per 1M tokens, and a
   `long_context` block if the model bills long requests at a higher rate. `null` marks an unknown price; the report
   flags the model instead of guessing.

3. **Try it**:

   ```bash
   crbench probe --models my-model                          # one tiny call per level
   crbench estimate --set full --models my-model            # prompt sizes and projected cost of one pass
   crbench run --set full --models my-model --prs sentry__93824
   crbench judge --set full --models my-model --prs sentry__93824
   ```

   On the trial pull request, check the output tokens per level: a `default` that thinks as long as `xhigh` is the same
   level, and a level that never finishes within the output cap needs a lower one.

4. **Run, judge, check and report**:

   ```bash
   crbench run --set full --models my-model --repeats 1-3
   crbench judge --set full --models my-model --repeats 1-3
   crbench check --set full --models my-model --repeats 1-3
   crbench report --set full --repeats 1-3 --frontier --name full-r123
   python scripts/verify_report.py full-r123
   ```

   A new model is judged by the same panel as everything else, so its scores are comparable with the published ones.
   Rebuilding `full-r123` with it changes the tie groups (they are computed over all configurations), not the other
   models' scores.

## Use another prompt

Point `prompt.system` or `prompt.user` in `configs/runs.yaml` at your files, or keep them and run a control as
`scripts/control_prompt.py` does (separate run and judged directories, so nothing published is touched). A run made
with another prompt is redone, never mixed with the old one, because every run records its prompt's hash.

## Change the judges

The pool and its order are in `configs/judges.yaml`; each judge has a route, a model id, `params` added to every call
and `drop` for parameters its route refuses. A model is judged by the first three pool judges outside its family.
Changing the pool changes every model's panel, so judge everything again (`crbench judge --force`) before comparing.
`observers` judge every model without voting, which is a cheap way to see how a candidate judge would agree with the
panel.

## Ask your own questions

Most questions need no new runs: `results/dataset/` has every review, finding, verdict and cost
([DATASET.md](DATASET.md)), and `scripts/analyze.py` shows how the write-up's tables are computed from it.
`crbench report --set full --models a,b --tiers low --repeats 1-3 --name mine` builds a report of any slice in
`reports/mine/`.
