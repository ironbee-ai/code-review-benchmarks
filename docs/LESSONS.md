# Lessons from running it

What went wrong, or nearly did, in 8,000 reviews and about 600,000 judge calls, and what the harness does about it.
Most of it applies to any benchmark that calls many LLM APIs.

## Providers and routes

- **Pin the provider.** The same open model behaves differently on different hosts. DeepSeek V4 Pro on one host cut
  long generations with an error and mapped `low` to `high`; another ran it with thinking off when no effort was sent;
  others answered 30,000 to 42,000 output tokens on the same pull request. Every OpenRouter model here names one
  provider with fallbacks off (`provider` in `configs/models.yaml`), and every run records the provider that served
  it; a run served elsewhere would show.
- **Routes stall.** Grok 4.7 on one route stopped answering long requests a few minutes into the run while short
  calls kept working. A one-PR trial on the largest pull request before a pass (`crbench run --prs ...`) catches this
  kind of thing cheaply.
- **Not every model is on every account.** GLM 5.3 on Bedrock is limited to eligible accounts; it ran on Z.AI's own
  endpoint through OpenRouter. `crbench probe` makes one tiny call per model, level and judge before anything costs
  money.
- **Upstream rate limits.** A judge can be rate-limited upstream for an hour while its route stays up. The calls fail
  with 429s, and whatever the pipeline does with a failed call decides what that costs you (see the next section).

## Silent fallbacks

- **The dedup step falls back quietly.** The benchmark's duplicate-grouping step, after three failed attempts on a
  review, records "no duplicates" and moves on. Twice, judge calls failed in bulk (a credit refusal storm, an upstream
  rate limit), and the step saved all-singleton groups for hundreds of reviews. Nothing in its exit status says so.
  The fix was to count successful dedup calls against the reviews that need one (two findings or more) after every
  judging pass, and to ask again for exactly the reviews that fell back. Groups only keep a matched finding's
  duplicates from counting as false positives, so a fallback can only lower precision. Both times the repaired
  groups made no difference to the scores: no duplicates at all in one case, four in the other, all among findings
  that matched nothing.
- **Credit is reserved, not spent.** OpenRouter holds back the possible cost of every request in flight. With little
  credit left and many calls in flight, it refuses calls (402) even though the balance would cover what they actually
  cost. The judge proxy now holds such a call and asks again instead of passing the refusal on to the step.
- **Check what a step dropped.** The benchmark's matching step gives a review 30 minutes and drops it if it takes
  longer. One review with 538 findings needed 36 minutes of the slowest judge; the lanes allow 90. `crbench check`
  verifies that every configuration has a verdict from every judge on every pull request.

## Models

- **Some models cannot stop thinking.** Mistral Large 4 with reasoning on spent its whole 65,536-token budget thinking
  on every real pull request tried; Claude Haiku 5.5 at its highest level did the same on one pull request, seven
  calls in a row, in two passes, and finished it in one call in the third. Give runs a hard output cap and a time
  limit, and record a review that never finishes as empty rather than retrying forever.
- **Replies break.** 121 of the 7,980 reviews needed a second call because the reply was not the JSON asked for. A
  reply that finished but carries broken JSON still holds complete findings; keeping them (`salvage_findings`) loses
  less than discarding the review. A reply cut at the output cap is not a finished review and stays empty.
- **Models loop.** One review wrote 538 findings, 359 with the same title. Expect outliers that stress every later
  step, judging cost included (judging grows with findings times goldens).
- **Defaults are not documented levels.** One model's default looked like its highest level and turned out to think
  about a third as long; probing the output tokens per level on one pull request settles it.

## Judges

- **Judges ramble.** At low effort a judge sometimes explains itself before the JSON it was asked for, which the
  benchmark's parser rejects; reading the reply's last JSON object recovers the judge's own verdict.
- **Types drift.** A judge once wrote its confidence as the string "0.9", which crashed the step; a `"false"` written as
  a string would have counted as a match. Retype what a step compares before it reads it.
- **Judging is noise too.** Three configurations judged twice from scratch, same reviews, moved by 0 to 1.6 points of
  F2. Part of what looks like run-to-run variation is the judges'.

## Infrastructure

- **Thread safety of connection pools.** The local proxy first shared one HTTP client across threads; under load it
  closed sockets other threads were still using, and 0.1% of judge calls failed (the steps asked them again). One
  client per incoming connection fixed it. Broken lines in the usage logs were the visible symptom; check for them.
- **Resume, never restart.** Every step skips what is already done and redoes only what is missing or was made under
  other settings, so a killed run, an exhausted credit or a closed laptop costs nothing but time.

## Numbers

- **Run it more than once.** Across three passes with nothing changed, a configuration's F2 moved by a median of 2.6
  points and at most 7.5. One run of 50 pull requests ranks configurations less reliably than its decimals suggest;
  report groups, not ranks.
- **Tokens are not tokens.** Claude's tokenizer counts the same prompt as about 1.6 times as many tokens as GPT's.
- **Prices hide rules.** Cache writes cost more than plain input on some routes, which a single pass never earns back;
  some models bill every token of a long request at a higher rate; some bill half off-peak; introductory prices end.
  `configs/pricing.yaml` writes down the rule used, and the "uncached" cost keeps providers comparable.
