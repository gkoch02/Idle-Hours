# Final Empty Buckets

After broad harvesting, strict filtering, targeted sparse-bucket hunting, and a final surgical pass against the cached Gutenberg corpus, these buckets remain empty:

- `h3_late_past`
- `h3_quarter_toish`
- `h5_late_past`
- `h6_late_past`

## What was tried

- broad regex harvesting across Gutenberg texts
- strict filtering to remove generic daypart noise
- targeted phrase search against sparse and empty buckets
- final direct search for explicit phrases in cached texts
- web search checks for representative exact phrases on Project Gutenberg

## Current conclusion

These appear to be genuine corpus gaps in the currently harvested public-domain source set, not just an extraction miss.

## Recommended next options

1. Accept these as gaps and allow neighboring-bucket fallback.
2. Expand to additional public-domain sources beyond current Gutenberg cache.
3. Manually curate a small number of quotes for these exact buckets.
