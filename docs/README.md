# Hidden Links — Project Documentation

Detailed build documentation for Hidden Links: an Agentic GraphRAG system over Indian listed-company governance disclosures that answers questions three ways (RAG, GraphRAG, Agentic GraphRAG) and measures where each succeeds or fails.

## Documents

| File | What it answers |
| --- | --- |
| [PRD.md](PRD.md) | What we are building and why: problem, users, goals, requirements, success metrics, scope, risks |
| [TRD.md](TRD.md) | Technical requirements: stack decisions, repo layout, config, data models, database and graph schemas, interfaces, API, performance, security, testing, standards |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design: context, containers, build pipeline, online layer, sequences, agent loop, deployment, cross-cutting concerns, ADRs |

## Build phases (follow in order)

| Phase | File | Outcome |
| --- | --- | --- |
| 0 | [phase-00-setup-and-spikes.md](phases/phase-00-setup-and-spikes.md) | Environment, Neo4j, run store, LLM gateway with cache/cost, parser chosen |
| 1 | [phase-01-data-acquisition.md](phases/phase-01-data-acquisition.md) | All target filings obtained and registered with provenance |
| 2 | [phase-02-extraction-pilot.md](phases/phase-02-extraction-pilot.md) | Parsing, sections, chunks, grounded extraction, validation; quality and cost measured on 5 companies |
| 3 | [phase-03-entity-resolution-and-graph.md](phases/phase-03-entity-resolution-and-graph.md) | Full extraction, entity resolution, graph + vector index, one-command rebuild |
| 4 | [phase-04-rag-baseline.md](phases/phase-04-rag-baseline.md) | Shared answer contract, tracer, RAG pipeline |
| 5 | [phase-05-evaluation-set-and-runner.md](phases/phase-05-evaluation-set-and-runner.md) | Verified question set, scorers, calibrated judge, runner, statistics |
| 6 | [phase-06-graphrag.md](phases/phase-06-graphrag.md) | GraphRAG pipeline, tuned on dev, evaluated on test |
| 7 | [phase-07-agentic-graphrag.md](phases/phase-07-agentic-graphrag.md) | Agent with tools, guardrails, calculator, verifier, budgets |
| 8 | [phase-08-api-and-dashboard.md](phases/phase-08-api-and-dashboard.md) | API and five-page dashboard, demo mode |
| 9 | [phase-09-hardening.md](phases/phase-09-hardening.md) | Tests, Docker, seeding, CI, README, results, fresh-clone test |
| 10 | [phase-10-demo-and-submission.md](phases/phase-10-demo-and-submission.md) | Demo video and submission |

## Every phase file contains

Overview (goal, why, prerequisites, outputs, requirement links) · concepts to learn · files created · numbered implementation steps with code/Cypher/SQL sketches · tests · error handling · exit criteria with how to check · pitfalls and debugging · hand-off to the next phase.

## Accuracy note

Code, Cypher and configuration are **sketches** that show structure. Library APIs, database syntax, filing formats, regulations and prices change. Anything marked **Verify** must be checked against current official documentation before use. Numbers such as thresholds and budgets are starting values to tune, not facts.
