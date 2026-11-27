
## Replay join: per-class miss rates (2026-11-28, claude)
`scripts/replay_join.py` (run from the dir holding `out/`, `PYTHONPATH=src`): 3,060 NM/HD/NF runs, 735 maps,
overall miss 4.34%. Class comes from the map (walks, curves, legs), result from the replay.
Contrast = class miss rate minus the rest of the same map; "adj" also matches leg distance + tempo.
Map-clustered bootstrap 95% CI. Findings (adj, pp): curvy_stream +4.5 [2.2, 6.8], hexagon +6.1, pentagon +4.5,
star +2.2 [1.8, 2.6], square +2.4, line +2.7, circle +1.6 (CI spans 0), triangle 0.0.
Raw star (+4.2) is half "wide jumps are hard"; the adjusted number is the honest one.
Caveats: DT/HR/EZ/RX runs skipped; walks/curves not yet in `FEATURE_VERSION`/recommend (Phase E bump pending);
labels are the owner's subjective review (20 windows), so detector precision is only spot-checked.
Squares on soft rain 696-713 are a real 4-note square lap repeated at ~100 ms, not false positives.
