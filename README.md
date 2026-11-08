# llm-guard-gateway

**An input-guarding proxy for LLM APIs.** It inspects every prompt in three stages (regex rules → Japanese NER → local-LLM judgement), then masks, blocks or holds it before anything reaches the external model. Ships with a synthetic-data evaluation harness that measures miss rate, over-block rate and latency.

> 作業中。README の各章は実装と一緒に埋めていきます。
