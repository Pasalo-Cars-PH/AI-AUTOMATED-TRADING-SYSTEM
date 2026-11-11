# XAU/USD M5 export audit — execution status

## Status

The export/audit script is committed on branch `audit/xauusd-m5-export-pdh-pdl` as commit `887ffa51f81217282de7f76b60fbeac20f0e92f7`.

**The live data export has not been executed from this ChatGPT environment.** This environment does not expose the Render runtime's `TWELVE_DATA_API_KEY` or an authenticated Twelve Data execution context. Therefore no CSV values, timestamps, PDH/PDL results, or closed-candle outcome are claimed here.

## Run in the trusted environment

From the repository root, where `TWELVE_DATA_API_KEY` is already configured:

```bash
python scripts/export_xauusd_m5.py
```

The script calls the existing `app.main.fetch_data("XAU/USD", "5min", 900)`, writes `reports/xauusd_m5_900.csv`, and writes the generated evidence report to `reports/xauusd_m5_audit.md`.

It prints row count, first/last timestamp, M5 closed-candle check, previous UTC date coverage, recomputed PDH/PDL compared with 4164.86/4164.61, cache key/age visible in that process, and source function file/line locations. The report includes inspected source excerpts.

## Important limitations

- Existing `fetch_data` sends `timezone=UTC` but returns only `res["values"]`; the function does not expose the response-level timezone metadata. The script explicitly documents this limitation and treats naive timestamps as UTC based on the request parameter.
- The export deliberately calls `fetch_data` directly, bypassing the wrapper cache. Its cache report is only an inspection of the local Python process and cannot establish another Render worker's in-memory cache age.
- 900 M5 rows may not cover a complete previous UTC day. The report labels missing/partial date coverage rather than presenting incomplete extrema as definitive PDH/PDL.
- No strategy thresholds, trading permissions, environment variables, or safety locks are modified. Do not enable live trading as part of this audit.
