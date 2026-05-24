# Freight & Shipment Analytics Platform

> End-to-end supply chain analytics platform built for the **freight forwarding & 3PL** domain. Ingests global shipment data into a Kimball star schema warehouse, calculates supply chain KPIs (OTIF, transit variance, mode scorecard), predicts late deliveries with machine learning, and serves it through **two dashboards** — a deployed Streamlit web app and a Power BI report.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://varad-supply-chain-analytics.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white)](https://www.python.org/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![PowerBI](https://img.shields.io/badge/Power%20BI-Desktop-F2C811?logo=powerbi&logoColor=black)](#power-bi-dashboard)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-1.8-F7931E?logo=scikit-learn&logoColor=white)](https://scikit-learn.org/)

**🔗 Live app:** <https://varad-supply-chain-analytics.streamlit.app/>

![Dashboard overview](docs/screenshots/overview.png)

---

## What this is

DSV, DHL, Kuehne+Nagel, and every other global 3PL live and die by the same metrics: **On-Time In-Full delivery, transit-time predictability, and cost-to-serve.** This project mirrors the data products a Supply Chain Analyst would build in that environment — not a generic e-commerce dashboard.

The platform ingests **180,519 shipment records** spanning five global markets (USCA, LATAM, Europe, Pacific Asia, Africa), models the data dimensionally so it's BI-tool ready, surfaces the headline operational KPIs as SQL views, adds a predictive layer to flag late-delivery risk **before** the SLA breach, and presents the results through both an interactive web dashboard (Streamlit) and a business-intelligence report (Power BI).

The Streamlit app is deployed publicly so you can click the link above and explore it yourself.

---

## Key findings

### The shipping mode paradox

The faster the promised delivery mode, the **worse** the on-time performance:

| Mode | SLA promise | Actual avg | On-time % | Late % | Volume |
|---|---|---|---|---|---|
| Standard Class | 4 days | 4.00 days | **60.2%** | 38.1% | 107,752 |
| Same Day | 0 days | 0.48 days | 52.2% | 45.7% | 9,737 |
| Second Class | 2 days | 3.99 days | 20.3% | 76.6% | 35,216 |
| First Class | 1 day | 2.00 days | **0.0%** | **95.3%** | 27,814 |

**First Class shipments missed SLA on every single one of 27,814 orders.** This isn't a logistics failure — it's a structural SLA misalignment. The physical network can reliably deliver in 2-4 days; the company keeps selling 1-day. The corrective action is commercial (reset SLA), not operational.

### Systemic, not regional or segment-specific

The OTIF rate sits between **40.49% and 41.45% across all five global markets** — a spread of less than one percentage point. Customer-segment late percentages are equally uniform (54.72% – 55.07%). When the problem is uniform across markets and customer types, the cause is *upstream of operations* — in how SLAs are set at the policy level, not in regional execution.

### Network health

- **OTIF rate: 40.88%** — far below the 90%+ industry benchmark for healthy 3PLs
- **Late delivery rate: 54.83%** — more orders are late than on-time
- **Late-delivery classifier: 87% precision** — when the model flags an order as late, operations can confidently expedite

---

## Architecture

```
┌────────────────┐   ┌──────────────┐   ┌──────────────────┐   ┌─────────────┐
│  Raw CSV       │──▶│  Python      │──▶│  MySQL 8.0       │──▶│  SQL Views  │
│  (180k orders) │   │  Ingestion   │   │  (Star Schema)   │   │  (KPIs)     │
└────────────────┘   └──────────────┘   └──────────────────┘   └──────┬──────┘
                                                                       │
              ┌────────────────────────────────────────────────────────┤
              ▼                                                        ▼
     ┌─────────────────┐                                  ┌──────────────────────┐
     │  scikit-learn   │                                  │  Dashboards          │
     │  Delay Predictor│─────────────────────────────────▶│  Streamlit + PowerBI │
     └─────────────────┘                                  └──────────┬───────────┘
                                                                     │
                                                                     ▼
                                                          ┌─────────────────────┐
                                                          │  Streamlit Cloud    │
                                                          │  (Public Live URL)  │
                                                          └─────────────────────┘
```

**Data model**: Kimball star schema — one fact (`fact_orders`, 180,519 rows) and five conformed dimensions (`dim_customer`, `dim_product`, `dim_geography`, `dim_shipping_mode`, `dim_date`).

**Production pattern**: in development the Streamlit app reads live from MySQL; for the public deployment, view results are materialized to parquet (`data/snapshot/`) and the app switches to file mode via the `USE_SNAPSHOT` flag — keeping the demo self-contained.

---

## Tech stack

| Layer | Tool | Why this choice |
|---|---|---|
| Warehouse | MySQL 8.0 (Docker) | OLTP standard; what most 3PLs already run on |
| Ingestion | Python · pandas · SQLAlchemy · PyMySQL | Production-standard analyst toolchain |
| Modeling | Kimball star schema | Universal pattern that maps directly to BI consumption |
| ML | scikit-learn (LogReg + HistGradientBoosting) | Compared a linear baseline against gradient boosting |
| Dashboards | Streamlit + Plotly **and** Power BI | Web-app for live demo; Power BI for the enterprise BI story |
| Deployment | Streamlit Community Cloud + GitHub | Live public URL with zero infra cost |

---

## KPIs implemented

| KPI | Definition | Business meaning |
|---|---|---|
| **OTIF rate** | % delivered on time AND not cancelled | Headline supply chain KPI |
| **Avg transit variance** | AVG(actual − scheduled days) | Network predictability |
| **Late delivery rate** | % of orders with status = 'Late delivery' | Direct customer impact |
| **Shipping mode scorecard** | On-time %, avg delay, volume by mode | Capacity / SLA reset signal |
| **Market performance** | OTIF + margin by global market | Regional ops health |
| **Top problem routes** | Worst origin → destination pairs | Targeted fix list |
| **Segment profitability** | Margin + late % by customer type | Cost-to-serve insight |
| **Predicted delay risk** | ML model probability per order | Proactive intervention signal |

---

## Streamlit dashboard (live demo)

The web app at <https://varad-supply-chain-analytics.streamlit.app/> has four tabs: overview, mode/market performance, problem routes, and a live ML delay predictor.

### Overview — headline KPIs at a glance
![Overview tab](docs/screenshots/overview.png)

### Mode & Market Performance — the shipping mode paradox visualized
![Mode performance](docs/screenshots/mode-performance.png)

### Late Delivery Predictor — live ML inference
![Predictor](docs/screenshots/predictor.png)

---

## Power BI dashboard

A native Power BI report built on the same MySQL warehouse — three pages covering the same KPI surface, designed for the enterprise BI environment most 3PLs run on. The `.pbix` file (`supply_chain_dashboard.pbix`) is committed in this repo: download and open it with Power BI Desktop to explore interactively.

### Overview page — KPIs and demand trends
![Power BI Overview](docs/screenshots/powerbi-overview.png)

### Mode & Market Performance — the shipping mode story
![Power BI Mode & Market](docs/screenshots/powerbi-mode-market.png)

### Routes & Segments — problem routes and customer segment profitability
![Power BI Routes & Segments](docs/screenshots/powerbi-routes-segments.png)

---

## Repository structure

```
supply-chain-analytics/
├── data/
│   ├── raw/                    # DataCoSupplyChainDataset.csv (gitignored, 95 MB)
│   └── snapshot/               # Parquet snapshots for the live deployment
├── sql/
│   ├── ddl/                    # Star schema definition (MySQL)
│   └── analytics/              # KPI view definitions
├── src/
│   ├── db.py                   # SQLAlchemy engine factory
│   ├── ingestion/
│   │   └── load_data.py        # CSV → MySQL pipeline
│   ├── models/
│   │   ├── train.py            # Trains LR + GBM, saves the best
│   │   └── late_delivery_classifier.joblib
│   └── dashboard/
│       ├── app.py              # Streamlit application
│       └── snapshot.py         # Exports view results to parquet for deployment
├── supply_chain_dashboard.pbix # Power BI report
├── docker-compose.yml          # Local MySQL container
└── requirements.txt
```

---

## Local setup

### Prerequisites
- Python 3.10+ (3.13 recommended)
- Docker Desktop
- MySQL Workbench (for SQL inspection)
- Power BI Desktop (Windows only — for the .pbix)
- The Kaggle dataset CSV: <https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis>

### Get running in 10 minutes

```bash
# 1. Python environment
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env

# 2. Start MySQL
docker compose up -d

# 3. Drop the Kaggle CSV into data/raw/, then:

# 4. Create the schema (in MySQL Workbench): sql/ddl/01_schema.sql

# 5. Load 180k rows into the warehouse
python src/ingestion/load_data.py

# 6. Build the KPI views (in MySQL Workbench): sql/analytics/kpis.sql

# 7. Train the classifier
python src/models/train.py

# 8. Launch the Streamlit dashboard
streamlit run src/dashboard/app.py

# 9. (Optional) Open the Power BI report
#    File → Open → supply_chain_dashboard.pbix
```

---

## ML model details

Binary classifier predicting `delivery_status = 'Late delivery'` from order attributes at the moment of order placement.

**Features**: shipping mode, customer segment, product category, origin market, payment type, scheduled days, item quantity, sales, profit, discount rate, day-of-week, month.

**Models compared**:
| Model | ROC-AUC | F1 | Precision (late) | Recall (late) |
|---|---|---|---|---|
| Logistic Regression | 0.7405 | 0.6727 | 88.7% | 54.2% |
| HistGradientBoosting (chosen) | **0.7455** | **0.6771** | 87.2% | 55.4% |

**Honest framing**: The two models perform similarly, suggesting the signal is primarily linear — shipping mode dominates. High precision (87%) makes the model useful for *flagging* high-risk orders to expedite; lower recall is the honest limitation. Next iterations would add route-distance features and threshold-tune for the business cost of false alarms vs missed late deliveries.

---

## Roadmap

- [x] **Phase 1** — MySQL warehouse with Kimball star schema + KPI views
- [x] **Phase 2** — Late delivery classifier (scikit-learn)
- [x] **Phase 3** — Streamlit dashboard with live ML predictor
- [x] **Phase 4** — Public deployment on Streamlit Community Cloud
- [x] **Phase 5** — Power BI dashboard (.pbix) connecting to the warehouse
- [ ] **Phase 6** — Route-distance feature engineering + threshold tuning
- [ ] **Phase 7** — Productionize transformations with dbt

---

## Data

**DataCo Smart Supply Chain** dataset on Kaggle — 180,519 orders across 5 global markets, 4 shipping modes, ~50 product categories. <https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis>
