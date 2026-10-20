# Code review benchmark: set `frontier`

Profile `core` (api, bug, concurrency, data, doc_defect, perf, security, test_gap); F2 alongside F1; repeats [1]; three judges per model from outside its family, majority vote. Costs at list price per pull request.

## Every configuration

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 45.8 | 76.7 | 57.4 | 67.6 | 54.3–81.2 | 6.8 | 0.87 | 0.87 | 4,435 | 2,426 | 58 | 79 | 0.83 |
| claude-fable-5.1 | default | 39.7 | 72.1 | 51.2 | 62.0 | 45.7–78.4 | 7.5 | 1.08 | 1.08 | 8,610 | 6,169 | 105 | 144 | 0.84 |
| gpt-6-astra | low | 70.8 | 39.5 | 50.7 | 43.4 | 26.7–56.8 | 2.3 | 0.50 | 0.41 | 393 | 72 | 9 | 13 | 0.97 |
| claude-fable-5.1 | xhigh | 35.2 | 72.1 | 47.3 | 59.6 | 44.2–74.1 | 8.4 | 1.61 | 1.61 | 19,373 | 16,661 | 216 | 313 | 0.85 |
| gpt-6-astra | xhigh | 46.3 | 44.2 | 45.2 | 44.6 | 28.9–59.5 | 3.9 | 0.81 | 0.74 | 7,041 | 6,464 | 119 | 169 | 0.94 |
| gpt-6-astra | default | 47.1 | 37.2 | 41.6 | 38.8 | 22.9–52.7 | 3.3 | 0.54 | 0.44 | 1,041 | 560 | 17 | 28 | 0.97 |

## Vendor default tier

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | default | 39.7 | 72.1 | 51.2 | 62.0 | 45.7–78.4 | 7.5 | 1.08 | 1.08 | 8,610 | 6,169 | 105 | 144 | 0.84 |
| gpt-6-astra | default | 47.1 | 37.2 | 41.6 | 38.8 | 22.9–52.7 | 3.3 | 0.54 | 0.44 | 1,041 | 560 | 17 | 28 | 0.97 |

## Best tier per model

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 45.8 | 76.7 | 57.4 | 67.6 | 54.3–81.2 | 6.8 | 0.87 | 0.87 | 4,435 | 2,426 | 58 | 79 | 0.83 |
| gpt-6-astra | low | 70.8 | 39.5 | 50.7 | 43.4 | 26.7–56.8 | 2.3 | 0.50 | 0.41 | 393 | 72 | 9 | 13 | 0.97 |

## F2 by language (best tier per model; n = pull requests x repeats)

| config | Go (n=2) | Java (n=2) | Python (n=2) | Ruby (n=2) | TypeScript (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 62.5* | 57.7* | 83.3* | 49.2* | 80.0* |
| gpt-6-astra/low | 32.3* | 52.6* | 42.9* | 31.2* | 55.6* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by repo (best tier per model; n = pull requests x repeats)

| config | cal.com (n=2) | discourse (n=2) | grafana (n=2) | keycloak (n=2) | sentry (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 80.0* | 49.2* | 62.5* | 57.7* | 83.3* |
| gpt-6-astra/low | 55.6* | 31.2* | 32.3* | 52.6* | 42.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by pr_size_category (best tier per model; n = pull requests x repeats)

| config | large (n=4) | medium (n=2) | small (n=4) |
|---|---|---|---|
| claude-fable-5.1/low | 70.0* | 52.6* | 71.4* |
| gpt-6-astra/low | 51.6* | 18.5* | 34.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by change_type (best tier per model; n = pull requests x repeats)

| config | feature (n=9) | performance (n=1) |
|---|---|---|
| claude-fable-5.1/low | 68.0* | 62.5* |
| gpt-6-astra/low | 46.2* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by review_difficulty (best tier per model; n = pull requests x repeats)

| config | moderate (n=3) | subtle (n=6) | very_subtle (n=1) |
|---|---|---|---|
| claude-fable-5.1/low | 62.5* | 68.1* | 76.9* |
| gpt-6-astra/low | 16.7* | 44.9* | 100.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by requires_context (best tier per model; n = pull requests x repeats)

| config | cross_file (n=9) | file (n=1) |
|---|---|---|
| claude-fable-5.1/low | 66.8* | 83.3* |
| gpt-6-astra/low | 45.2* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## Recall by golden category (best tier per model)

| config | api (n=6) | bug (n=24) | concurrency (n=2) | data (n=1) | doc_defect (n=2) | security (n=5) | test_gap (n=3) |
|---|---|---|---|---|---|---|---|
| claude-fable-5.1/low | 100.0 | 79.2 | 100.0 | 100.0 | 100.0 | 20.0 | 66.7 |
| gpt-6-astra/low | 50.0 | 45.8 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |

## Recall by golden severity (best tier per model)

| config | Critical (n=3) | High (n=17) | Low (n=8) | Medium (n=15) |
|---|---|---|---|---|
| claude-fable-5.1/low | 33.3 | 100.0 | 75.0 | 60.0 |
| gpt-6-astra/low | 0.0 | 76.5 | 0.0 | 26.7 |

## Each judge's own F2 (judge sensitivity)

| config | claude-opus-5.5 | gemini-4-argon | gpt-6.1-sol | grok-4.7 |
|---|---|---|---|---|
| claude-fable-5.1/low |  | 67.9 | 67.9 | 67.9 |
| claude-fable-5.1/default |  | 62.0 | 62.0 | 66.0 |
| claude-fable-5.1/xhigh |  | 59.6 | 59.6 | 60.1 |
| gpt-6-astra/low | 43.4 | 43.4 |  | 45.9 |
| gpt-6-astra/default | 38.8 | 38.8 |  | 41.3 |
| gpt-6-astra/xhigh | 44.6 | 42.3 |  | 46.9 |

## Not run

| model | tier | why |
|---|---|---|
| mistral-large-4 | default | reasoning on: 19 min and 61k output tokens on the trial PR, no answer in 25 min on the smallest (it loops) |
| mistral-large-4 | xhigh | reasoning on: as default |
