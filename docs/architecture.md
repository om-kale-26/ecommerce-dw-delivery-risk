# Architecture

```
Kaggle CSVs (Olist Brazilian E-Commerce — 9 files)
        │  download_data.py
        ▼
   Python ingestion (load_raw.py)  ──► raw.*  (Bronze: as-received, all-String, audit-logged)
        │
        ▼
   Validation + cleaning (clean.py)  ──► staging.*  (Silver: typed, deduped, standardized)
        │                                     │
        │                                     └──► raw.rejected_rows (quarantine)
        ▼
   Dimension/fact loaders  ──► warehouse.*  (Gold: star schema, dim_customer is SCD Type 2)
        │
        ▼
   analytics/business_queries.sql  +  Power BI (via ClickHouse ODBC connector)
```

## Why ClickHouse, Docker, DBeaver, Power BI

- **ClickHouse**: columnar OLAP engine — the point of a data *warehouse* project is
  demonstrating you understand analytical (not transactional) storage. MergeTree
  tables, `PARTITION BY`, `LowCardinality`, and window functions all show up here.
- **Docker Compose**: reproducible local infra — anyone cloning the repo runs one
  command and has the exact same warehouse.
- **DBeaver**: the SQL client used to run DDL and the analytics query library
  directly against ClickHouse (native TCP driver, port 9000, or HTTP, port 8123).
- **Power BI**: the presentation/analytics layer. Connects over the ClickHouse ODBC
  driver (self-managed ClickHouse has no built-in cloud connector) — see
  `powerbi/README.md`.

## Repository structure

```
olist-dw/
├── docker-compose.yml          # spins up ClickHouse
├── .env.example                # copy to .env
├── requirements.txt
├── data/raw/                   # Kaggle CSVs land here (gitignored)
├── ingestion/
│   ├── download_data.py        # pulls + renames the Kaggle dataset
│   ├── config.py
│   └── load_raw.py             # CSV -> raw.* (Bronze)
├── transformations/
│   ├── validation.py           # row-level validation rules
│   └── clean.py                # raw.* -> staging.* (Silver)
├── warehouse/
│   ├── ddl/{raw,staging,dimensions,facts}/*.sql
│   ├── load_dimensions.py      # staging.* -> warehouse.dim_* (Gold)
│   └── load_facts.py           # staging.* -> warehouse.fact_* (Gold)
├── analytics/
│   └── business_queries.sql    # 22-query library, also feeds Power BI
├── powerbi/
│   ├── README.md               # ODBC setup + connection steps
│   └── dax_measures.md         # suggested DAX measures
├── tests/
│   └── test_data_quality.py
└── docs/
    ├── architecture.md         # this file
    └── data_dictionary.md
```

## v2 roadmap (worth mentioning in the LinkedIn post as "what's next")

- Incremental loads instead of full refresh (simulate a new-file-per-day pattern)
- Resolve `fact_*.customer_key` against the SCD2 version current *on the order
  date*, not load date
- Bring in `geolocation.csv` for a real lat/lng seller↔customer distance metric
- Airflow orchestration once the manual pipeline is stable
