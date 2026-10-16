"""
Late-delivery risk model for the Olist ClickHouse warehouse.

Pipeline: ClickHouse features -> time-based split -> baselines + Keras MLP
          -> metrics CSV / PR-curve plot -> predictions written back to ClickHouse.

Run from the project root:   python ml/train.py
"""
import os
import random
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import clickhouse_connect
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix,
                             precision_recall_curve, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------- config
SEED = 42
MODEL_VERSION = "mlp_v1"
BATCH_ID = "test_batch_v1"
PRED_DB = os.getenv("PREDICTIONS_DATABASE", "default")   # change if you want another DB
REPORTS = ROOT / "reports"
ARTIFACTS = ROOT / "ml" / "artifacts"
REPORTS.mkdir(exist_ok=True)
ARTIFACTS.mkdir(parents=True, exist_ok=True)

random.seed(SEED)
np.random.seed(SEED)

NUM = ["purchase_dow", "purchase_hour", "purchase_month", "promised_days",
       "item_count", "seller_count", "product_count", "items_value",
       "freight_total", "freight_ratio", "total_weight_g", "total_volume_cm3",
       "same_state"]
CAT = ["customer_state", "seller_state"]

# ---------------------------------------------------------------- load
client = clickhouse_connect.get_client(
    host=os.getenv("CLICKHOUSE_HOST", "localhost"),
    port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
    username=os.getenv("CLICKHOUSE_USER", "default"),
    password=os.getenv("CLICKHOUSE_PASSWORD", ""),
)
sql = (ROOT / "ml" / "delivery_features.sql").read_text()
df = client.query_df(sql)
print("Rows loaded:", len(df))
assert df["order_id"].is_unique, "Feature query returned duplicate order_ids - check grain!"

for col in NUM:
    df[col] = pd.to_numeric(df[col], errors="coerce")
for col in CAT:
    df[col] = df[col].fillna("unknown").astype(str).replace("", "unknown")
df = df.sort_values("purchase_ts").reset_index(drop=True)

y = df["label"].astype(int).values
print(f"Late-delivery base rate: {y.mean():.2%}  "
      f"(period {df['purchase_ts'].min():%Y-%m-%d} to {df['purchase_ts'].max():%Y-%m-%d})")

# ---------------------------------------------------------------- time-based split
n = len(df)
i1, i2 = int(n * 0.70), int(n * 0.85)
tr, va, te = df.iloc[:i1], df.iloc[i1:i2], df.iloc[i2:]
ytr, yva, yte = y[:i1], y[i1:i2], y[i2:]
print(f"Train {len(tr)} | Val {len(va)} | Test {len(te)}")
print(f"Test period: {te['purchase_ts'].min():%Y-%m-%d} to {te['purchase_ts'].max():%Y-%m-%d}")

# preprocessing is fitted on TRAIN only
pre = ColumnTransformer([
    ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                      ("sc", StandardScaler())]), NUM),
    ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50,
                          sparse_output=False), CAT),
])
Xtr = pre.fit_transform(tr[NUM + CAT]).astype("float32")
Xva = pre.transform(va[NUM + CAT]).astype("float32")
Xte = pre.transform(te[NUM + CAT]).astype("float32")
feature_names = pre.get_feature_names_out()
assert np.isfinite(Xtr).all() and np.isfinite(Xva).all() and np.isfinite(Xte).all()


# ---------------------------------------------------------------- helpers
def pick_threshold(y_true, p):
    """Threshold maximising F1 on the VALIDATION set."""
    prec, rec, thr = precision_recall_curve(y_true, p)
    f1 = 2 * prec[:-1] * rec[:-1] / (prec[:-1] + rec[:-1] + 1e-12)
    return float(thr[np.argmax(f1)])


def evaluate(name, p_val, p_test):
    t = pick_threshold(yva, p_val)
    pred = (p_test >= t).astype(int)
    tn, fp, fn, tp = confusion_matrix(yte, pred, labels=[0, 1]).ravel()
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    row = {"model": name,
           "roc_auc": roc_auc_score(yte, p_test),
           "pr_auc": average_precision_score(yte, p_test),
           "precision": precision, "recall": recall, "f1": f1,
           "threshold": t, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
           "test_base_rate": yte.mean()}
    print(f"{name:8s} ROC-AUC {row['roc_auc']:.3f} | PR-AUC {row['pr_auc']:.3f} | "
          f"P {precision:.3f} | R {recall:.3f} | F1 {f1:.3f} | thr {t:.3f}")
    return row


# ---------------------------------------------------------------- baselines
rows, test_scores = [], {}
baselines = [("Dummy", DummyClassifier(strategy="prior")),
             ("LogReg", LogisticRegression(max_iter=2000, class_weight="balanced")),
             ("HistGB", HistGradientBoostingClassifier(random_state=SEED))]
hgb = None
for name, model in baselines:
    model.fit(Xtr, ytr)
    pv, pt = model.predict_proba(Xva)[:, 1], model.predict_proba(Xte)[:, 1]
    rows.append(evaluate(name, pv, pt))
    test_scores[name] = pt
    if name == "HistGB":
        hgb = model

# ---------------------------------------------------------------- MLP
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

tf.random.set_seed(SEED)
mlp = keras.Sequential([
    layers.Input(shape=(Xtr.shape[1],)),
    layers.Dense(64, activation="relu"),
    layers.Dropout(0.2),
    layers.Dense(32, activation="relu"),
    layers.Dense(1, activation="sigmoid"),
])
mlp.compile(optimizer=keras.optimizers.Adam(1e-3), loss="binary_crossentropy",
            metrics=[keras.metrics.AUC(name="roc_auc"),
                     keras.metrics.AUC(curve="PR", name="pr_auc")])
pos = ytr.mean()
mlp.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=100, batch_size=256,
        class_weight={0: 1.0, 1: (1 - pos) / pos},
        callbacks=[keras.callbacks.EarlyStopping(monitor="val_pr_auc", mode="max",
                                                 patience=5, restore_best_weights=True)],
        verbose=2)
pv_mlp = mlp.predict(Xva, verbose=0).ravel()
pt_mlp = mlp.predict(Xte, verbose=0).ravel()
mlp_row = evaluate("MLP", pv_mlp, pt_mlp)
rows.append(mlp_row)
test_scores["MLP"] = pt_mlp

# ---------------------------------------------------------------- reports
comp = pd.DataFrame(rows).round(4)
comp.to_csv(REPORTS / "model_comparison.csv", index=False)
print("\n", comp[["model", "roc_auc", "pr_auc", "precision", "recall", "f1"]].to_string(index=False))

plt.figure(figsize=(7, 5))
for name, p in test_scores.items():
    pr, rc, _ = precision_recall_curve(yte, p)
    plt.plot(rc, pr, label=f"{name} (PR-AUC {average_precision_score(yte, p):.3f})")
plt.axhline(yte.mean(), ls="--", c="grey", label=f"Base rate {yte.mean():.3f}")
plt.xlabel("Recall"); plt.ylabel("Precision")
plt.title("Late-delivery risk: precision-recall on held-out test period")
plt.legend(); plt.tight_layout()
plt.savefig(REPORTS / "pr_curves.png", dpi=150)
plt.close()

# which features matter? (permutation importance of the tree model on validation data)
imp = permutation_importance(hgb, Xva, yva, scoring="average_precision",
                             n_repeats=5, random_state=SEED)
imp_df = (pd.DataFrame({"feature": feature_names, "importance": imp.importances_mean})
          .sort_values("importance", ascending=False))
imp_df.to_csv(REPORTS / "feature_importance.csv", index=False)
print("\nTop features (HistGB permutation importance):")
print(imp_df.head(10).to_string(index=False))

joblib.dump(pre, ARTIFACTS / "preprocessor.joblib")
mlp.save(ARTIFACTS / "mlp_v1.keras")

# ---------------------------------------------------------------- write predictions
thr = mlp_row["threshold"]
out = pd.DataFrame({
    "order_id": te["order_id"].values,
    "late_probability": pt_mlp.astype("float32"),
    "predicted_late": (pt_mlp >= thr).astype("uint8"),
    "actual_late": yte.astype("uint8"),        # for evaluation only
    "model_version": MODEL_VERSION,
    "batch_id": BATCH_ID,
})
client.command(f"""
CREATE TABLE IF NOT EXISTS {PRED_DB}.delivery_predictions
(
    order_id         String,
    scored_at        DateTime DEFAULT now(),
    late_probability Float32,
    predicted_late   UInt8,
    actual_late      UInt8,
    model_version    String,
    batch_id         String
)
ENGINE = MergeTree
ORDER BY (batch_id, order_id)
""")
# rerun-safe: remove this batch's earlier rows before inserting
client.command(
    f"ALTER TABLE {PRED_DB}.delivery_predictions DELETE "
    f"WHERE batch_id = '{BATCH_ID}' AND model_version = '{MODEL_VERSION}'",
    settings={"mutations_sync": 1})
client.insert_df(f"{PRED_DB}.delivery_predictions", out)
print(f"\nWrote {len(out)} predictions to {PRED_DB}.delivery_predictions")
print("Done. Results are in the reports/ folder.")
