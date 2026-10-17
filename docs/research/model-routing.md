# Model routing and task difficulty: research notes

Reference notes gathered on 2026-10-16 while designing the cascade rule in `graphs/lane.md`. They are background, not rules: the rule is in `graphs/lane.md`. Several figures come from secondary sources; each claim links its source, so check the original before relying on a number.

## 1. Difficulty can be measured as human time
METR measures difficulty as how long a skilled human takes, and capability as each model's
"time horizon": the task length it completes 50% (or 80%) of the time. Success falls off
along a logistic curve as tasks get longer.
- Near-100% on tasks under about 4 minutes; under 10% on tasks over about 4 hours (2025
  paper). The 50% horizon doubles roughly every 7 months.
- The 80% horizon is far shorter than the 50% one. In one analysis: 59 min at 50%, 15 min at
  80%.
- SWE-bench Verified annotates tasks into human-time buckets: <15 min, 15 min-1 h, 1-4 h,
  >4 h. METR found these annotations optimistic: the "<15 min" tasks averaged about 33 min
  for its baseliners.

Sources: https://www.alignmentforum.org/posts/deesrjitvXM4xYGZd/metr-measuring-ai-ability-to-complete-long-tasks
https://arxiv.org/pdf/2503.14499 · https://metr.org/blog/2025-07-14-how-does-time-horizon-vary-across-domains/
https://openai.com/es-ES/index/introducing-swe-bench-verified/

## 2. A strong planner with a cheaper executor works
- Aider's architect/editor mode: a strong model proposes, a cheaper model edits. o3 with
  GPT-4.1 reached 83% on Aider Polyglot at lower cost (a secondary report).
- Claude Code's `opusplan`: Opus plans, Sonnet executes.
- Anthropic's multi-agent research system: an Opus lead with Sonnet subagents beat a single
  Opus 4 agent by 90.2% on its internal research eval. Multi-agent runs used about 15x the
  tokens of a chat (a single agent, about 4x), and token use by itself explained 80% of the
  performance variance. The post also says each subagent needs an objective, an output
  format, guidance on the tools and sources to use, and clear task boundaries.
- Official Claude Code docs: route lower-cost work, such as exploration, to Haiku. The
  per-invocation `model` parameter overrides the definition.

Sources: https://codemyspec.com/blog/aider-review-2026
https://inventivehq.com/blog/opus-vs-sonnet-claude-code
https://www.anthropic.com/engineering/multi-agent-research-system
https://code.claude.com/docs/en/sub-agents

## 3. Verifying is usually easier than generating
- Weak generators make errors that are easier to detect.
- A verifier's skill tracks its own problem-solving skill.
- One secondary summary: a large verifier over a small generator gives big gains, while a
  small verifier over a large generator hurts. This is unverified.
- This supports reviewer >= builder.

Sources: https://arxiv.org/pdf/2509.17995v1 · https://www.alphaxiv.org/overview/2605.27564

## 4. Learned routers need outcome data
- RouteLLM (ICLR 2025) uses preference-trained routers and cuts cost more than 2x at the
  same quality.
- RouterBench, RouterEval and LLMRouterBench are routing benchmarks.
- IRT-Router (ACL 2025) uses item response theory: each model gets an ability score, each
  query a difficulty and a discrimination score. It is interpretable and handles cold
  starts.
- Agent-as-a-Router (2026): zero-shot LLM routers fall well short of the oracle, and
  information access is the bottleneck.

Sources: https://arxiv.org/html/2406.18665v2 · https://arxiv.org/pdf/2403.12031
https://arxiv.org/abs/2503.10657v1 · https://arxiv.org/pdf/2506.01048 · https://arxiv.org/pdf/2606.22902

## 5. Cascades: try cheap, check, escalate
FrugalGPT, AutoMix. The design question is the escalation signal. Ours is the review
verdict.

Sources: https://arxiv.org/pdf/2603.04445 · https://arxiv.org/pdf/2310.12963

## 6. Models are poor judges of their own success
Models overestimate their success in advance on coding and agentic tasks, most on hard
tasks.

Sources: https://arxiv.org/html/2512.24661v1 · https://www.alphaxiv.org/abs/2605.23909

## Implications for the harness
- Tonight's cascade rule is consistent with all of the above:
  - lean light, because executors can be cheaper when the plan is good;
  - reviewer one tier up, because of the verifier gap;
  - escalate on a failed review, which is the cascade signal.
- The cheapest new signal: the work order states an estimated human-time bucket, using the
  SWE-bench buckets. It is interpretable, it lines up with public model time horizons, and
  it logs data.
- The principled future classifier: an IRT-style fit on our own lane outcomes. Each lane is
  an item, each tier an ability, and swings-to-land is the response. It needs the receipts
  that the cascade now records.
- Work-order quality, meaning delegation clarity, is a lever the harness controls directly.
