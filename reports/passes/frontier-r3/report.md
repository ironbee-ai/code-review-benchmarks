# Code review benchmark: set `frontier`

Profile `core` (api, bug, concurrency, data, doc_defect, perf, security, test_gap); F2 alongside F1; repeats [3]; three judges per model from outside its family, majority vote. Costs at list price per pull request.

## Every configuration

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 47.1 | 74.4 | 57.7 | 66.7 | 51.2–80.2 | 6.4 | 0.86 | 0.86 | 4,250 | 2,434 | 57 | 73 | 0.88 |
| claude-fable-5.1 | default | 41.8 | 76.7 | 54.1 | 65.7 | 51.2–79.3 | 7.6 | 1.07 | 1.07 | 8,454 | 5,931 | 91 | 166 | 0.83 |
| gpt-6-astra | low | 70.8 | 39.5 | 50.7 | 43.4 | 24.1–61.3 | 2.3 | 0.50 | 0.41 | 392 | 61 | 7 | 13 | 0.94 |
| claude-fable-5.1 | xhigh | 37.1 | 76.7 | 50.0 | 63.2 | 48.2–79.1 | 8.6 | 1.64 | 1.64 | 19,881 | 16,781 | 199 | 381 | 0.88 |
| gpt-6-astra | default | 56.2 | 41.9 | 48.0 | 44.1 | 25.6–59.7 | 3.1 | 0.54 | 0.44 | 1,025 | 579 | 17 | 27 | 0.94 |
| gpt-6-astra | xhigh | 43.9 | 41.9 | 42.9 | 42.3 | 25.9–53.5 | 4.0 | 0.85 | 0.75 | 7,273 | 6,683 | 136 | 199 | 0.97 |

## Vendor default tier

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | default | 41.8 | 76.7 | 54.1 | 65.7 | 51.2–79.3 | 7.6 | 1.07 | 1.07 | 8,454 | 5,931 | 91 | 166 | 0.83 |
| gpt-6-astra | default | 56.2 | 41.9 | 48.0 | 44.1 | 25.6–59.7 | 3.1 | 0.54 | 0.44 | 1,025 | 579 | 17 | 27 | 0.94 |

## Best tier per model

| model | tier | P | R | F1 | F2 | F2 95% CI | findings/PR | $/PR | $/PR uncached | out tok/PR | reasoning/PR | median s | p90 s | κ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| claude-fable-5.1 | low | 47.1 | 74.4 | 57.7 | 66.7 | 51.2–80.2 | 6.4 | 0.86 | 0.86 | 4,250 | 2,434 | 57 | 73 | 0.88 |
| gpt-6-astra | low | 70.8 | 39.5 | 50.7 | 43.4 | 24.1–61.3 | 2.3 | 0.50 | 0.41 | 392 | 61 | 7 | 13 | 0.94 |

## F2 by language (best tier per model; n = pull requests x repeats)

| config | Go (n=2) | Java (n=2) | Python (n=2) | Ruby (n=2) | TypeScript (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 62.5* | 37.0* | 81.4* | 52.6* | 82.2* |
| gpt-6-astra/low | 33.3* | 52.6* | 42.9* | 20.8* | 62.5* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by repo (best tier per model; n = pull requests x repeats)

| config | cal.com (n=2) | discourse (n=2) | grafana (n=2) | keycloak (n=2) | sentry (n=2) |
|---|---|---|---|---|---|
| claude-fable-5.1/low | 82.2* | 52.6* | 62.5* | 37.0* | 81.4* |
| gpt-6-astra/low | 62.5* | 20.8* | 33.3* | 52.6* | 42.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by pr_size_category (best tier per model; n = pull requests x repeats)

| config | large (n=4) | medium (n=2) | small (n=4) |
|---|---|---|---|
| claude-fable-5.1/low | 72.4* | 40.5* | 69.0* |
| gpt-6-astra/low | 51.6* | 18.5* | 34.9* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by change_type (best tier per model; n = pull requests x repeats)

| config | feature (n=9) | performance (n=1) |
|---|---|---|
| claude-fable-5.1/low | 67.3* | 58.8* |
| gpt-6-astra/low | 46.2* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by review_difficulty (best tier per model; n = pull requests x repeats)

| config | moderate (n=3) | subtle (n=6) | very_subtle (n=1) |
|---|---|---|---|
| claude-fable-5.1/low | 50.0* | 69.9* | 71.4* |
| gpt-6-astra/low | 16.7* | 44.9* | 100.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## F2 by requires_context (best tier per model; n = pull requests x repeats)

| config | cross_file (n=9) | file (n=1) |
|---|---|---|
| claude-fable-5.1/low | 65.8* | 83.3* |
| gpt-6-astra/low | 45.2* | 0.0* |

`*` fewer than 10 pull requests: read as a hint, not a result.

## Recall by golden category (best tier per model)

| config | api (n=6) | bug (n=24) | concurrency (n=2) | data (n=1) | doc_defect (n=2) | security (n=5) | test_gap (n=3) |
|---|---|---|---|---|---|---|---|
| claude-fable-5.1/low | 100.0 | 75.0 | 100.0 | 100.0 | 100.0 | 20.0 | 66.7 |
| gpt-6-astra/low | 50.0 | 45.8 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 |

## Recall by golden severity (best tier per model)

| config | Critical (n=3) | High (n=17) | Low (n=8) | Medium (n=15) |
|---|---|---|---|---|
| claude-fable-5.1/low | 33.3 | 100.0 | 75.0 | 53.3 |
| gpt-6-astra/low | 0.0 | 82.4 | 12.5 | 13.3 |

## Each judge's own F2 (judge sensitivity)

| config | claude-opus-5.5 | gemini-4-argon | gpt-6.1-sol | grok-4.7 |
|---|---|---|---|---|
| claude-fable-5.1/low |  | 66.9 | 64.9 | 66.9 |
| claude-fable-5.1/default |  | 65.7 | 61.8 | 69.7 |
| claude-fable-5.1/xhigh |  | 61.3 | 63.2 | 59.6 |
| gpt-6-astra/low | 43.4 | 43.4 |  | 43.4 |
| gpt-6-astra/default | 41.7 | 44.1 |  | 41.7 |
| gpt-6-astra/xhigh | 44.6 | 42.3 |  | 42.3 |

## Not run

| model | tier | why |
|---|---|---|
| mistral-large-4 | default | reasoning on: 19 min and 61k output tokens on the trial PR, no answer in 25 min on the smallest (it loops) |
| mistral-large-4 | xhigh | reasoning on: as default |
