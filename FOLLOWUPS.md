# Follow-ups

Deferred work items — deliberately carved out of a larger change so the
landed commit stayed focused and low-risk. Not a bug tracker; each item
is something the codebase is fine without but would be cleaner with.

## Quiet-hours state machine consolidation

**Context.** The runtime-architecture lockdown (commit
`ec92075 Lock down the runtime module architecture`) consolidated most
of the seams between `run_clock.py` and the seven `runtime_*` siblings,
but deliberately skipped one piece: the quiet-hours state machine. That
one is behaviour-affecting on the live appliance (panel ghosting,
shutdown preamble, manual-vs-scheduled interaction) and is isolated
enough to land separately and revert without unpicking the rest.

**What's still inlined.** `run_clock.py` main loop at roughly lines
826–862 still owns:

- the `_was_quiet` local flag tracking whether the *previous* tick was
  in quiet hours,
- the "just entered quiet" branch that pushes `--quiet-image` to the
  panel and records the quiet-hours telemetry entry,
- the "just exited quiet" branch that clears `state.last_bucket` /
  `state.last_quote_id` to force a repaint on the next normal tick.

`runtime_actions.action_quiet` open-codes the same
`last_bucket = None; last_quote_id = None` clear for the manual-quiet
toggle path (around `runtime_actions.py:186–188`) — so the exit-from-quiet
logic lives in two places.

**Proposal.** Move to `runtime_quiet.py`:

- `compute_quiet(args, state, now) -> bool` — combines scheduled window
  (`in_quiet_hours`) with `state.manual_quiet` into one boolean.
- `enter_quiet(args, state, time_str)` — pushes `--quiet-image` under
  `state.render_lock`, writes the quiet-hours telemetry entry.
- `exit_quiet(state)` — clears `last_bucket` / `last_quote_id` under
  `state.lock`. Called by both the main loop (scheduled exit) and
  `action_quiet` (manual wake).

Move `_was_quiet` onto `RuntimeState.was_quiet: bool` — no lock needed
since only the main loop writes it.

Loop body then becomes roughly:

```python
if compute_quiet(args, state, time_str):
    if not state.was_quiet:
        enter_quiet(args, state, time_str)
        state.was_quiet = True
    if _loop_sleep(state, max(1, args.interval_seconds)):
        break
    continue

if state.was_quiet:
    exit_quiet(state)
    state.was_quiet = False
```

**Why it's isolated.** Tests exercising this live in
`tests/test_run_clock.py` under the quiet-hours classes (grep
`-k quiet`); `test_concurrency.py` also touches it for lock contention.
The changes are mostly moving code; the tricky bit is that
`state.render_lock` must still wrap the `_display_quiet_image` call
(see `runtime_quiet.py:41`), so the function boundary needs to keep that
contract.

**Verification when picking it up.**

```bash
pytest tests/test_run_clock.py -v -k quiet
pytest tests/test_concurrency.py -v
python3 run_clock.py --once --buttons-off  # smoke
# Manual: set --quiet-start / --quiet-end to a 2-minute window spanning
# "now", watch stderr for exactly one "quiet hours start" log and one
# "quiet hours end" log as the window opens and closes.
```

**Source.** The approved plan for this work lives at
`/root/.claude/plans/lock-down-the-new-immutable-chipmunk.md` §7; treat
this section as the canonical in-repo reference since that path is
machine-local.
