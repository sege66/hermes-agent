# Cron: require explicit provider and model (ki66 local)

Local-only note, kept out of `website/docs/` so the upstream docs page stays unmodified
(Docusaurus builds every file under `website/docs/`). The text below used to sit in
`website/docs/user-guide/features/cron.md`, right before "Skill-backed cron jobs".
Implementation: `cron/jobs_ki66.py`.

To make every **active LLM** cron job carry an explicit `provider` and `model` — so a new
unpinned job is rejected at creation or edit time instead of silently following the main
agent model (which `hermes model` can later move) — fail the fleet closed:

```yaml
cron:
  require_explicit_provider_model: true
```

The check runs when the job is persisted, before any schedule fires; a missing field raises
`Active LLM cron jobs require explicit provider and model when
cron.require_explicit_provider_model=true`. Jobs run with `--no-agent` are exempt (they never
call a model).
