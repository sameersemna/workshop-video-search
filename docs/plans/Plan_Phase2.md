# Phase 2 Implementation Plan

## Objective
Deliver a balanced Phase 2 that hardens reliability, security, and testability while improving developer velocity and user experience.

## Implementation Strategy
- Sequencing: balanced hardening plus feature improvements
- Ownership model: vertical slices with explicit handoff boundaries
- Refactor policy: major refactors allowed, gated by milestones

## High-Priority Risks Addressed
1. Insecure CORS policy and missing request hardening
2. Direct route access to search internals
3. Concurrency and cleanup risks in background/transcription flow
4. No reliable test baseline or CI quality gates
5. Frontend polling and API error resilience gaps

## Vertical Slice Work Packages

### Slice A: Ingestion and Processing Reliability
Owner: Agent A

Scope:
- Add strict validation for YouTube and upload inputs
- Centralize backend settings and startup validation
- Consolidate executor usage and queue lifecycle semantics
- Add deterministic cleanup for temp audio/frame artifacts
- Make transcript segment indexing idempotent on retries

Success Criteria:
- Upload and YouTube ingestion reject invalid input deterministically
- Reprocessing does not duplicate indexed segments
- Temp artifacts are cleaned up under normal and failure paths

### Slice B: Search Contract and API Consistency
Owner: Agent B

Scope:
- Replace route-level private collection access with service/repository methods
- Add bounded query validation for top_k, search type, and scope
- Normalize error envelopes and response consistency
- Add basic search telemetry for latency and error categories

Success Criteria:
- Routes no longer access private search fields
- Search APIs enforce limits and return consistent error contracts

### Slice C: Frontend Architecture and Resilience
Owner: Agent C

Scope:
- Refactor app orchestration into controller/layout and reusable hooks
- Add typed API error model, timeout, and retry strategy
- Improve polling with backoff and idle-aware behavior
- Remove unsafe casts and improve loading/empty/error states

Success Criteria:
- API failures surface clear UI feedback and recovery options
- Polling load is reduced during idle/stable periods
- Core search flows remain type-safe end-to-end

### Slice D: Test and CI Quality Gates
Owner: Agent D

Scope:
- Backend pytest baseline and critical-path service/route tests
- Frontend Vitest baseline and core component/service tests
- CI workflow with lint, type-check, tests
- Staged coverage targets per milestone

Success Criteria:
- CI runs on pull requests with deterministic pass/fail behavior
- Critical flows have automated regression tests

## Milestones and Dependencies

### M0: Foundation
- Add plan document and scaffolding
- Add initial CI pipeline and test runners

### M1: Reliability Baseline
Depends on: M0
- Complete Slice A hardening minimums

### M2: Contract and UI Stabilization
Depends on: M1
- Execute Slice B and Slice C in parallel after interface freeze

### M3: Test Enforcement
Depends on: M2
- Expand tests and enforce stronger CI gates

### M4: Security and Operations Readiness
Depends on: M3
- Tightened CORS, request throttling, operational runbooks

## Agent Handoff Tasks

### Task A1
Implement backend settings module and migrate environment reads.

### Task A2
Add upload and URL validation with explicit size/type/model constraints.

### Task A3
Refactor background/transcription execution boundaries and cleanup handling.

### Task B1
Introduce service methods to replace direct `_collection` usage in routes.

### Task B2
Add unified search query guards and error response envelopes.

### Task C1
Refactor frontend orchestration and centralize API error handling.

### Task C2
Implement backoff polling and resilient empty/loading/error UI states.

### Task D1
Bootstrap backend/frontend test folders, setup files, and smoke tests.

### Task D2
Create CI workflow for lint, type-check, and tests across both stacks.

## Definition of Done for Phase 2
- Critical reliability and security gaps are remediated
- Core user workflows are covered by automated tests
- CI enforces quality gates on pull requests
- Service and UI architecture are easier to extend safely
