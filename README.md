# Freight & Shipment Analytics Platform

End-to-end supply chain analytics platform built for the **freight forwarding & contract logistics** domain (DSV-style). Ingests global shipment data into a **MySQL** dimensional warehouse, calculates supply chain KPIs (OTIF, transit time variance, freight performance, carrier scorecard), predicts late deliveries with machine learning, and serves it through interactive dashboards.

## Why this project

DSV and most global 3PLs live and die by the same KPIs: **On-Time In-Full delivery, transit time predictability, cost-to-serve, and capacity utilization**. This platform mirrors the data products a Supply Chain Data Analyst would actually build on the job, not a generic e-commerce dashboard.

## Architecture

```
┌────────────────┐   ┌──────────────┐   ┌──────────────────┐   ┌─────────────┐
│  Raw CSV       │──▶│  Python      │──▶│  MySQL 8.0       │──▶│  SQL Views  │
│  (180k orders) │   │  Ingestion   │   │  (Star Schema)   │   │  (KPIs)     │
└────────────────┘   └──────────────┘   └──────────────────┘   └──────┬──────┘
                                                                       │
                              ┌────────────────────────────────────────┤
                              ▼                                        ▼
                     ┌─────────────────┐                      ┌─────────────────┐
                     │  scikit-learn   │                      │  Streamlit      │
                     │  Delay Predictor│─────────────────────▶│  + Power BI     │
                     └─────────────────┘                      └─────────────────┘
                                                                       │
                                                                       ▼
                                                              ┌─────────────────┐
                                                              │  Streamlit Cloud│
                                                              │  Deployment     │
                                                              └─────────────────┘
```

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Storage | MySQL 8.0 (Docker) | Industry-standard OLTP; widely used at 3PLs |
| Query / Admin | **MySQL Workbench** | GUI for writing and running SQL |
| Ingestion | Python + pandas + SQLAlchemy + PyMySQL | Standard for analyst pipelines |
| Modeling | Kimball star schema | Universal warehouse pattern; interview gold |
| ML | scikit-learn | Logistic Regression + Gradient Boosting for delay prediction |
| Dashboard | Streamlit + Power BI | Streamlit for interactive ML; Power BI for the BI-native story |
| Deployment | Streamlit Community Cloud + Docker | Free, fast, public-link-able |

## Dataset

**DataCo Smart Supply Chain** — 180,519 orders with shipping mode, real vs scheduled delivery days, late delivery flag, geographic data across 5 markets (USCA, LATAM, Europe, Pacific Asia, Africa), product hierarchy, and profitability.

Download from Kaggle: <https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis>

Place `DataCoSupplyChainDataset.csv` in `data/raw/`.

## KPIs implemented

| KPI | Definition | Business meaning |
|---|---|---|
| **OTIF rate** | % of orders delivered on time AND not cancelled | The headline supply chain KPI |
| **Avg transit time variance** | AVG(actual_days - scheduled_days) | How predictable is the network |
| **Late delivery rate** | % orders with status = 'Late delivery' | Direct customer impact metric |
| **Shipping mode scorecard** | On-time %, avg delay, volume by mode | Where to push capacity |
| **Market performance** | OTIF + margin by global market | Regional ops health |
| **Top problem routes** | Worst origin→destination pairs | Targeted fix list |
| **Segment profitability** | Margin + late % by customer type | Cost-to-serve insight |
| **Predicted delay risk** | ML model output per order | Proactive intervention |

## Project structure

```
supply-chain-analytics/
├── data/
│   ├── raw/                    # DataCoSupplyChainDataset.csv goes here
│   └── processed/
├── sql/
│   ├── ddl/                    # Schema definitions
│   └── analytics/              # KPI views
├── src/
│   ├── ingestion/              # CSV → MySQL pipeline
│   ├── models/                 # ML training + prediction
│   └── dashboard/              # Streamlit app
├── notebooks/                  # EDA, modeling exploration
├── deployment/                 # Docker, Streamlit config
└── docs/                       # Architecture, data dictionary
```



### Prerequisites
- Python 3.10+
- Docker Desktop (running)
- **MySQL Workbench** installed ([download here](https://dev.mysql.com/downloads/workbench/))
- The Kaggle dataset CSV

### 1. Python environment
```bash
python -m venv venv
# macOS/Linux:
source venv/bin/activate
# Windows:
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
```

### 2. Start MySQL
```bash
docker compose up -d
docker ps          # confirm supply_chain_mysql is "healthy" (may take ~30s on first run)
```

### 3. Connect MySQL Workbench
Open MySQL Workbench, click the **+** next to "MySQL Connections":
- **Connection Name**: `supply_chain_local`
- **Hostname**: `127.0.0.1`
- **Port**: `3306`
- **Username**: `analyst`
- Click **Test Connection** → enter password `analyst` → save

Double-click the connection to open it.

### 4. Drop in the dataset
Download `DataCoSupplyChainDataset.csv` from the Kaggle link above and place it in `data/raw/`.

### 5. Create the schema
In Workbench: **File → Open SQL Script** → pick `sql/ddl/01_schema.sql` → click the lightning bolt ⚡ (Execute) — should run in under a second. Refresh the SCHEMAS panel on the left; you'll see 6 tables under `supply_chain`.

### 6. Run the ingestion
Back in your terminal:
```bash
python src/ingestion/load_data.py
```
Final output prints row counts per table.

### 7. Build the KPI views
In Workbench: **File → Open SQL Script** → `sql/analytics/kpis.sql` → ⚡ Execute.

### 8. Sanity check
In a Workbench query tab:
```sql
SELECT * FROM vw_kpi_summary;
SELECT * FROM vw_shipping_mode_scorecard;
SELECT * FROM vw_market_performance;
```

If you see numbers in the result grid — **Phase 1 is done**.

## Roadmap

- [x] **Phase 1** — Warehouse + ingestion + KPI views *(this commit)*
- [ ] **Phase 2** — Late delivery prediction model (scikit-learn)
- [ ] **Phase 3** — Streamlit dashboard with live predictor
- [ ] **Phase 4** — Power BI dashboard (.pbix connecting to MySQL)
- [ ] **Phase 5** — Dockerize + deploy to Streamlit Community Cloud
- [ ] **Phase 6** — README polish, architecture diagram, screenshots
