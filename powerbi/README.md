# Connecting Power BI to ClickHouse (self-managed, Docker on Windows)

Power BI has no built-in ClickHouse connector for **self-managed** ClickHouse
(the built-in "ClickHouse" connector some docs mention is for ClickHouse Cloud
only). For a Docker-hosted instance like this project's, you go through the
**ClickHouse ODBC driver**. This is well-trodden and works fine for a local
portfolio project.

## 1. Install the ClickHouse ODBC driver

1. Download the Windows installer from
   https://github.com/ClickHouse/clickhouse-odbc/releases
   (get `clickhouse-odbc-<version>-win64.msi`).
2. Run the installer.

## 2. Create a System DSN

1. Open **ODBC Data Sources (64-bit)** from Windows search.
2. Go to the **System DSN** tab → **Add** → pick **ClickHouse ODBC Driver (Unicode)**.
3. Fill in:
   - **Host:** `localhost`
   - **Port:** `8123` (HTTP interface — matches what's exposed in `docker-compose.yml`)
   - **Database:** `warehouse`
   - **User:** `default`
   - **Password:** (blank, unless you set one in `.env`)
4. Click **Test** to confirm it connects, then **OK**.

## 3. (Optional but nicer) Install the official ClickHouse Power BI connector

This gives you a native "ClickHouse" entry in Power BI's Get Data list instead of
the generic ODBC dialog, and folds queries better.

1. Create the folder `Documents\Power BI Desktop\Custom Connectors` if it doesn't exist.
2. Download the latest release from
   https://github.com/ClickHouse/power-bi-clickhouse and place the `.mez` file there.
3. In Power BI Desktop: **File → Options and settings → Options → Security → Data
   Extensions** → set **"Allow any extension to load without validation or warning"**.
4. Restart Power BI Desktop.

## 4. Connect in Power BI Desktop

- **With the custom connector:** Get Data → search "ClickHouse" → enter server
  (`localhost`), port, database (`warehouse`), credentials.
- **With plain ODBC (no extra install needed):** Get Data → **ODBC** → pick the DSN
  you created in step 2.

Choose **Import** mode for this project (dataset is small, ~100k orders — Import
is simpler and faster than DirectQuery for a portfolio dashboard). Use DirectQuery
only if you want the report to reflect live changes without refreshing.

## 5. What to pull in

Rather than importing raw tables and building joins in Power BI, import the *results*
of the relevant queries from `analytics/business_queries.sql` as separate Power
Query steps — this keeps your model simple and mirrors real BI practice (thin
semantic layer, business logic lives in SQL). At minimum, bring in:

- Q1 (monthly revenue/orders/units) → line/bar charts
- Q5 / Q6 (category revenue + share) → bar chart + a treemap
- Q8 / Q9 (seller-state and customer-state revenue) → **map visuals**
- Q13 / Q14 (delivery performance) → KPI cards + a bar chart by state
- Q16 / Q17 (review scores, and score vs. lateness) → bar chart + a callout card
- Q19 (payment type) → donut chart

See `powerbi/dax_measures.md` for a few measures worth adding once these are in.

## 6. Suggested dashboard pages (good screenshots for LinkedIn)

1. **Sales Overview** — revenue trend, AOV, MoM growth, top categories
2. **Geography** — map of revenue by customer state, map of revenue by seller state
3. **Delivery Performance** — on-time % KPI card, delay by state, late-vs-review-score
4. **Customer Segmentation** — RFM scatter/table, repeat vs one-time revenue split
