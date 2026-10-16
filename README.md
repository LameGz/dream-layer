# Dream Layer

**Randomly pair the fragments a workflow leaves behind, then offer observations and questions for human review.**

[中文](README.zh-CN.md) · [Agent skill](skills/dream/SKILL.md) · [Design and review notes](docs/brainstorm/) · [CI](https://github.com/LameGz/dream-layer/actions/workflows/test.yml)

Dream Layer is an experimental REM layer for agent workflows. It collects selected, rejected, hesitant and discarded material, pairs fragments without semantic similarity, asks a model to explore the collision, and screens the results. The morning report contains at most three candidates by default. People decide what is useful; dream output does not execute tasks or feed itself back into the material pool.

## Run a simulated night

Requires Python 3.11+; CI uses Python 3.12. Runtime dependencies are PyYAML and the OpenAI SDK. Run from the checkout so the configuration files are available.

```bash
git clone https://github.com/LameGz/dream-layer.git
cd dream-layer
python -m venv .venv
```

Activate with `.venvScriptsActivate.ps1` in Windows PowerShell or `source .venv/bin/activate` on macOS/Linux, then install:

```bash
python -m pip install -e ".[dev]"
```

Create `config/rhythm.local.yaml` with the following configuration. It uses the included demo seed and manual drops, disables the example personal-directory scans, and disables webhook delivery. This local file is Git-ignored. Its `collectors` mapping replaces the default mapping as a whole.

```yaml
collectors:
  demo: {}
  drop:
    - name: manual
      path: data/drop
  read_disk: []
webhook_url_env: ""
quiet_cycle: { mode: "off" }
```

```bash
python -m dreamlayer run --once --fake
```

This runs collection, pairing, simulated generation and screening, then writes records under `data/`. Insufficient material produces an explanation. `--fake` replaces the model engine; it still reads configured sources and writes files. Its output is for checking the pipeline.

## Collect, inspect, confirm

```text
drop / file sources
    → privacy and retention filtering → pool → random pairs
    → model collision → screening → morning report
    → human confirmation → confirmation log and metrics
```

```bash
python -m dreamlayer drop "discarded design: put every module in one process" --tag discarded --origin manual
python -m dreamlayer run --once --fake
python -m dreamlayer review
python -m dreamlayer metrics
```

Material tags are `selected`, `rejected`, `hesitated`, `discarded` and `unknown`. Weights come from `config/weights.yaml`. Pairing considers tags, origins, time buckets and coverage, without selecting pairs by semantic similarity. Each fragment participates in at most one pair per night.

Review only confirms candidates you judge useful: `recall`, `trend` or `cross_time`. Skipping is valid. To confirm directly, copy the actual ID from the morning report:

```bash
python -m dreamlayer confirm 2026-10-16-abcdef012345-01 cross_time
```

The ID above illustrates the format; replace it with an existing `dream_id`. Agents may use `review --batch "actual-id:cross_time"` to record a judgment the user has already made, rather than make that judgment themselves.

## Scheduling and record identity

`python -m dreamlayer run` starts a persistent process. Defaults are collection at 02:30, dreaming at 03:00 and screening at 05:00, in local time. The process must remain running. `run --once` executes a full cycle immediately. Startup includes a catch-up check; `quiet_cycle` can reduce runs to alternate days after a period without confirmations.

The recent-material window includes the previous calendar day and material already collected today, with older history sampled separately. Ingestion and pruning use the same retention cutoff, so an expired source cannot immediately re-enter the pool.

Each run has a separate 12-character `attempt_id`. New dream IDs are `YYYY-MM-DD-<attempt_id>-NN`. Repeating a run on the same day preserves earlier dream records and uses new IDs. Legacy `YYYY-MM-DD-NN` IDs remain readable and confirmable.

| Path | Contents |
|---|---|
| `data/drop/`, `data/pool/` | Incoming fragments and material pool |
| `data/dreams/attempts/<date>/` | Per-run dreams, metadata and confirmation state |
| `data/dreams/<date>.jsonl` | Compatibility view of the latest run |
| `data/journal/attempts/<date>/` | Per-run Markdown journals for new runs |
| `data/journal/<date>.md`, `data/morning/<date>.md` | Daily display views, updated by subsequent runs |
| `data/reflux_log.jsonl`, `data/report/` | Human confirmations, metrics and charts |

Older dreams can be confirmed by ID; `review --date` reads the latest candidate view for that date. Pool retention does not automatically delete journals or archives.

## Configuration and real engines

| File | Controls |
|---|---|
| `config/weights.yaml` | Tag weights, history sampling and coverage weights |
| `config/rhythm.yaml` | Schedule, water level, pair constraints, collectors, report limit |
| `config/rhythm.local.yaml` | Local top-level overrides; nested mappings are replaced |
| `config/privacy.yaml` | Path exclusions, redaction, origin switches, retention, privacy mode |
| `config/engine.yaml` | OpenAI-compatible endpoint, model and key environment variable name |

The checked-in rhythm configuration contains example local collection paths. Replace these with sources you choose before using real data. The default `privacy.mode: open` allows material content to be sent to the configured model endpoint; see `engine.yaml` for that endpoint. Supply `DREAM_LLM_API_KEY` through the environment, then run without `--fake`.

For a local model, set `privacy.mode: local_only` and use a loopback `engine.base_url`; non-local engine addresses are rejected. Also disable or review webhook settings if all processing must remain local: engine mode does not replace delivery configuration.

Optional `listen` serves `/drop` on `127.0.0.1:8787` by default, with `DREAM_DROP_TOKEN` for the token. Morning webhook delivery uses `DREAM_WEBHOOK_URL`. Inspect arguments with `python -m dreamlayer <subcommand> --help`.

## Working with the other projects

- [agent-tree](https://github.com/LameGz/agent-tree) records execution events and can explicitly submit failed, reworked and hesitant fragments, run a cycle, and read the morning report. It does not automatically enable Dream's persistent scheduler.
- [Synapse Graph Skills](https://github.com/LameGz/synapse-graph-skills) stores engineering memory. Dream observations do not automatically become Synapse facts; review them before using a memory proposal workflow.

## Validation and experimental limits

```bash
python -m pytest tests -q
```

On 2026-10-16, Ubuntu and Windows CI both reported **197 passed**. Regression coverage includes overnight material selection, same-day run identity, legacy confirmations, fake engines, expired material and unfinished frontmatter. Passing tests establish asserted behavior, not the usefulness of generated observations.

The value of random collisions remains a hypothesis. “95% noise” is a design expectation, not a measured rate. Historical evaluations and exit proposals live in [docs/brainstorm/](docs/brainstorm/); there is no mechanism that automatically archives the project. Many metrics read the latest daily views rather than every archived attempt. A/B attribution also has limitations with new attempt IDs, so current reports do not establish an experimental result.

Real model quality, long-term value, delivery services and host integrations require separate validation.

## License

[MIT License](LICENSE).
