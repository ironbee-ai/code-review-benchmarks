# Code review benchmark: set `frontier`

Profile `core` (api, bug, concurrency, data, doc_defect, perf, security, test_gap); F2 alongside F1; repeats [2]; three judges per model from outside its family, majority vote. Costs at list price per pull request.

## Every configuration

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 50.7 | 81.4 | 62.5 | 72.6 | 59.4–86.0 | 6.5 | 0.86 | 0.86 | 4,382 | 2,482 | 55 | 79 | 0.85 |
| claude-fable-5.1 | xhigh | 37.9 | 83.7 | 52.2 | 67.4 | 56.6–78.9 | 9.1 | 1.56 | 1.56 | 18,356 | 15,276 | 203 | 333 | 0.79 |
| gpt-6-astra | low | 69.6 | 37.2 | 48.5 | 41.0 | 21.9–55.2 | 2.2 | 0.50 | 0.41 | 368 | 58 | 7 | 12 | 0.93 |
| claude-fable-5.1 | default | 36.5 | 72.1 | 48.4 | 60.3 | 45.6–76.5 | 8.2 | 1.08 | 1.08 | 8,684 | 5,979 | 97 | 141 | 0.81 |
| gpt-6-astra | default | 51.4 | 41.9 | 46.2 | 43.5 | 25.5–58.8 | 3.4 | 0.54 | 0.44 | 1,118 | 627 | 13 | 41 | 0.90 |
| gpt-6-astra | xhigh | 41.9 | 41.9 | 41.9 | 41.9 | 27.0–53.4 | 4.2 | 0.89 | 0.79 | 8,026 | 7,443 | 119 | 204 | 0.84 |

## Vendor default tier

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | default | 36.5 | 72.1 | 48.4 | 60.3 | 45.6–76.5 | 8.2 | 1.08 | 1.08 | 8,684 | 5,979 | 97 | 141 | 0.81 |
| gpt-6-astra | default | 51.4 | 41.9 | 46.2 | 43.5 | 25.5–58.8 | 3.4 | 0.54 | 0.44 | 1,118 | 627 | 13 | 41 | 0.90 |

## Best tier per model

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 50.7 | 81.4 | 62.5 | 72.6 | 59.4–86.0 | 6.5 | 0.86 | 0.86 | 4,382 | 2,482 | 55 | 79 | 0.85 |
| gpt-6-astra | low | 69.6 | 37.2 | 48.5 | 41.0 | 21.9–55.2 | 2.2 | 0.50 | 0.41 | 368 | 58 | 7 | 12 | 0.93 |

## F2 by language (best tier per model; n = pull requests x repeats)

| config | Go (n=2) | Java (n=2) | Python (n=2) | Ruby (n=2) | TypeScript (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 50.0* | 83.3* | 90.9* | 58.3* | 82.2* |
| gpt-6-astra/low | 33.3* | 52.6* | 42.9* | 31.2* | 47.6* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by repo (best tier per model; n = pull requests x repeats)

| config | cal.com (n=2) | discourse (n=2) | grafana (n=2) | keycloak (n=2) | sentry (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 82.2* | 58.3* | 50.0* | 83.3* | 90.9* |
| gpt-6-astra/low | 47.6* | 31.2* | 33.3* | 52.6* | 42.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by pr_size_category (best tier per model; n = pull requests x repeats)

| config | large (n=4) | medium (n=2) | small (n=4) |
|---|---|---|---|
| claude-fable-5.1/low | 71.4* | 69.4* | 77.6* |
| gpt-6-astra/low | 51.6* | 0.0* | 34.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by change_type (best tier per model; n = pull requests x repeats)

| config | feature (n=9) | performance (n=1) |
|---|---|---|
| claude-fable-5.1/low | 71.7* | 83.3* |
| gpt-6-astra/low | 43.7* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by review_difficulty (best tier per model; n = pull requests x repeats)

| config | moderate (n=3) | subtle (n=6) | very_subtle (n=1) |
|---|---|---|---|
| claude-fable-5.1/low | 75.0* | 71.4* | 83.3* |
| gpt-6-astra/low | 16.7* | 41.9* | 100.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by requires_context (best tier per model; n = pull requests x repeats)

| config | cross_file (n=9) | file (n=1) |
|---|---|---|
| claude-fable-5.1/low | 74.2* | 41.7* |
| gpt-6-astra/low | 42.8* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## Recall by golden category (best tier per model)

| config | api (n=6) | bug (n=24) | concurrency (n=2) | data (n=1) | doc_defect (n=2) | security (n=5) | test_gap (n=3) |
|---|---|---|---|---|---|---|---|
| claude-fable-5.1/low | 83.3 | 87.5 | 100.0 | 100.0 | 100.0 | 20.0 | 100.0 |
| gpt-6-astra/low | 50.0 | 41.7 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |

## Recall by golden severity (best tier per model)

| config | Critical (n=3) | High (n=17) | Low (n=8) | Medium (n=15) |
|---|---|---|---|---|
| claude-fable-5.1/low | 33.3 | 94.1 | 87.5 | 73.3 |
| gpt-6-astra/low | 0.0 | 76.5 | 0.0 | 20.0 |

## Each judge's own F2 (judge sensitivity)

| config | claude-opus-5.5 | gemini-4-argon | gpt-6.1-sol | grok-4.7 |
|---|---|---|---|---|
| claude-fable-5.1/low |  | 72.9 | 70.8 | 73.2 |
| claude-fable-5.1/default |  | 60.3 | 60.3 | 58.6 |
| claude-fable-5.1/xhigh |  | 67.7 | 63.9 | 67.9 |
| gpt-6-astra/low | 41.0 | 41.0 |  | 35.9 |
| gpt-6-astra/default | 41.1 | 43.5 |  | 48.3 |
| gpt-6-astra/xhigh | 41.9 | 41.9 |  | 39.7 |

## Not run

| model | tier | why |
|---|---|---|
| mistral-large-4 | default | reasoning on: 19 min and 61k output tokens on the trial PR, no answer in 25 min on the smallest (it loops) |
| mistral-large-4 | xhigh | reasoning on: as default |
