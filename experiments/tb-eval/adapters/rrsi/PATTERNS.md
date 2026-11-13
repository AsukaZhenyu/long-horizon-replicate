# TB8 failure patterns

- **Wrong artifact shape**: the agent writes a file but not the exact path/format
  the hidden test reads.
- **Unvalidated submission**: the agent declares completion without running a
  local check or re-reading the artifact.
- **Budget burn**: repeated identical commands, or long exploratory reads that
  leave no time to finish.
- **Environment assumptions**: commands (`file`, `xxd`, `jq`) missing from the
  task image; the agent must fall back instead of repeating.
- **Partial correctness**: some checks pass, but the agent stops before the
  remaining required behavior is implemented.
