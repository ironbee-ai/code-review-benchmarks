# Code review benchmark: set `frontier`

Profile `core` (api, bug, concurrency, data, doc_defect, perf, security, test_gap); F2 alongside F1; repeats [1, 2, 3]; three judges per model from outside its family, majority vote. Costs at list price per pull request.

## Every configuration

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 47.8 | 77.5 | 59.2 | 69.0 | 60.1–77.1 | 6.6 | 0.86 | 0.86 | 4,356 | 2,448 | 56 | 77 | 0.85 |
| claude-fable-5.1 | default | 39.3 | 73.6 | 51.2 | 62.7 | 53.5–71.3 | 7.8 | 1.07 | 1.07 | 8,583 | 6,022 | 94 | 162 | 0.83 |
| gpt-6-astra | low | 70.4 | 38.8 | 50.0 | 42.6 | 32.0–52.0 | 2.3 | 0.50 | 0.41 | 384 | 64 | 7 | 13 | 0.95 |
| claude-fable-5.1 | xhigh | 36.8 | 77.5 | 49.9 | 63.5 | 55.0–71.6 | 8.7 | 1.60 | 1.60 | 19,203 | 16,225 | 212 | 366 | 0.84 |
| gpt-6-astra | default | 51.5 | 40.3 | 45.2 | 42.1 | 31.4–51.6 | 3.3 | 0.54 | 0.44 | 1,061 | 589 | 17 | 40 | 0.94 |
| gpt-6-astra | xhigh | 44.0 | 42.6 | 43.3 | 42.9 | 34.1–50.8 | 4.0 | 0.85 | 0.76 | 7,446 | 6,863 | 125 | 202 | 0.92 |

## Vendor default tier

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | default | 39.3 | 73.6 | 51.2 | 62.7 | 53.5–71.3 | 7.8 | 1.07 | 1.07 | 8,583 | 6,022 | 94 | 162 | 0.83 |
| gpt-6-astra | default | 51.5 | 40.3 | 45.2 | 42.1 | 31.4–51.6 | 3.3 | 0.54 | 0.44 | 1,061 | 589 | 17 | 40 | 0.94 |

## Best tier per model

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 47.8 | 77.5 | 59.2 | 69.0 | 60.1–77.1 | 6.6 | 0.86 | 0.86 | 4,356 | 2,448 | 56 | 77 | 0.85 |
| gpt-6-astra | low | 70.4 | 38.8 | 50.0 | 42.6 | 32.0–52.0 | 2.3 | 0.50 | 0.41 | 384 | 64 | 7 | 13 | 0.95 |

## F2 by language (best tier per model; n = pull requests x repeats)

| config | Go (n=6) | Java (n=6) | Python (n=6) | Ruby (n=6) | TypeScript (n=6) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 58.3* | 58.4* | 85.3* | 53.4* | 81.4* |
| gpt-6-astra/low | 33.0* | 52.6* | 42.9* | 27.8* | 55.3* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by repo (best tier per model; n = pull requests x repeats)

| config | cal.com (n=6) | discourse (n=6) | grafana (n=6) | keycloak (n=6) | sentry (n=6) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 81.4* | 53.4* | 58.3* | 58.4* | 85.3* |
| gpt-6-astra/low | 55.3* | 27.8* | 33.0* | 52.6* | 42.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by pr_size_category (best tier per model; n = pull requests x repeats)

| config | large (n=12) | medium (n=6) | small (n=12) |
|---|---|---|---|
| claude-fable-5.1/low | 71.3 | 54.1* | 72.7 |
| gpt-6-astra/low | 51.6 | 12.5* | 34.9 |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by change_type (best tier per model; n = pull requests x repeats)

| config | feature (n=27) | performance (n=3) |
|---|---|---|
| claude-fable-5.1/low | 69.0 | 68.6* |
| gpt-6-astra/low | 45.4 | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by review_difficulty (best tier per model; n = pull requests x repeats)

| config | moderate (n=9) | subtle (n=18) | very_subtle (n=3) |
|---|---|---|---|
| claude-fable-5.1/low | 62.5* | 69.8 | 76.9* |
| gpt-6-astra/low | 16.7* | 43.9 | 100.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by requires_context (best tier per model; n = pull requests x repeats)

| config | cross_file (n=27) | file (n=3) |
|---|---|---|
| claude-fable-5.1/low | 68.9 | 69.4* |
| gpt-6-astra/low | 44.4 | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## Recall by golden category (best tier per model)

| config | api (n=18) | bug (n=72) | concurrency (n=6) | data (n=3) | doc_defect (n=6) | security (n=15) | test_gap (n=9) |
|---|---|---|---|---|---|---|---|
| claude-fable-5.1/low | 94.4 | 80.6 | 100.0 | 100.0 | 100.0 | 20.0 | 77.8 |
| gpt-6-astra/low | 50.0 | 44.4 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |

## Recall by golden severity (best tier per model)

| config | Critical (n=9) | High (n=51) | Low (n=24) | Medium (n=45) |
|---|---|---|---|---|
| claude-fable-5.1/low | 33.3 | 98.0 | 79.2 | 62.2 |
| gpt-6-astra/low | 0.0 | 78.4 | 4.2 | 20.0 |

## Each judge's own F2 (judge sensitivity)

| config | claude-opus-5.5 | gemini-4-argon | gpt-6.1-sol | grok-4.7 |
|---|---|---|---|---|
| claude-fable-5.1/low |  | 69.3 | 67.9 | 69.3 |
| claude-fable-5.1/default |  | 62.7 | 61.3 | 64.7 |
| claude-fable-5.1/xhigh |  | 62.9 | 62.3 | 62.6 |
| gpt-6-astra/low | 42.6 | 42.6 |  | 41.7 |
| gpt-6-astra/default | 40.5 | 42.1 |  | 43.8 |
| gpt-6-astra/xhigh | 43.7 | 42.1 |  | 43.0 |

## Not run

| model | tier | why |
|---|---|---|
| mistral-large-4 | default | reasoning on: 19 min and 61k output tokens on the trial PR, no answer in 25 min on the smallest (it loops) |
| mistral-large-4 | xhigh | reasoning on: as default |
