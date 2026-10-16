# Suggested DAX Measures

Assumes you've imported query results as tables named roughly after their source
query (adjust table/column names to whatever you named them on import).

```DAX
Total Revenue = SUM('OrderItems'[total_amount])

Total Orders = DISTINCTCOUNT('OrderItems'[order_id])

Average Order Value = DIVIDE([Total Revenue], [Total Orders])

On-Time Delivery % =
DIVIDE(
    CALCULATE(COUNTROWS('Orders'), 'Orders'[is_delivered] = 1, 'Orders'[is_late] = 0),
    CALCULATE(COUNTROWS('Orders'), 'Orders'[is_delivered] = 1)
)

Average Review Score = AVERAGE('Reviews'[review_score])

Cancellation Rate =
DIVIDE(
    CALCULATE(COUNTROWS('Orders'), 'Orders'[order_status] = "canceled"),
    COUNTROWS('Orders')
)

Revenue MoM % =
VAR CurrentRevenue = [Total Revenue]
VAR PriorRevenue =
    CALCULATE([Total Revenue], DATEADD('DimDate'[date], -1, MONTH))
RETURN DIVIDE(CurrentRevenue - PriorRevenue, PriorRevenue)

Repeat Customer Revenue % =
DIVIDE(
    CALCULATE([Total Revenue], 'CustomerRFM'[frequency] > 1),
    [Total Revenue]
)
```

Tip: build a small explicit date table in Power BI (`Model view → New Table`, a
`CALENDAR()` DAX table) and mark it as the official Date table if you want
`DATEADD`/time-intelligence functions to work cleanly — don't rely solely on
`dim_date` from ClickHouse unless you also mark it as a date table in Power BI's
model settings.
