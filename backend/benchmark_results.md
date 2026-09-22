# Benchmark Results

Measured against **5,000,000** documents in the `events` collection.

| Query | No secondary indexes | With secondary indexes | Speedup |
|---|---|---|---|
| hourly | 3.060s | 0.110s | 27.86x |
| percentiles | 1.830s | 1.655s | 1.11x |
| cohort | 8.149s | 2.205s | 3.7x |
