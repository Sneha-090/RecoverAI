"""Train on disjoint synthetic customer contexts: python -m ML.train_model."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, brier_score_loss, confusion_matrix,
    f1_score, log_loss, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
CATEGORICAL = ["cause", "action_type", "cause_action"]
NUMERICAL = ["amount", "attempts", "days_since_failure", "past_rate"]


def prepare_features(frame):
    features = frame[["cause", "action_type", *NUMERICAL]].copy()
    features["cause_action"] = features["cause"] + "__" + features["action_type"]
    return features


def split_contexts(frame, seed=42):
    if frame["customer_id"].isna().any() or frame["customer_id"].nunique() < 2:
        raise ValueError("At least two non-null customer/context groups are required")
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
    train_indices, test_indices = next(splitter.split(frame, groups=frame["customer_id"]))
    train, test = frame.iloc[train_indices].copy(), frame.iloc[test_indices].copy()
    if train["recovered"].nunique() != 2 or test["recovered"].nunique() != 2:
        raise ValueError("Both partitions must contain recovered and unrecovered outcomes")
    return train, test


def build_model(seed=42):
    return Pipeline([
        ("preprocessor", ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("numerical", StandardScaler(), NUMERICAL),
        ])),
        ("classifier", LogisticRegression(max_iter=1000, random_state=seed)),
    ])


def evaluate_probabilities(target, probabilities):
    predicted = np.asarray(probabilities) >= 0.5
    return {
        "accuracy": float(accuracy_score(target, predicted)),
        "precision": float(precision_score(target, predicted, zero_division=0)),
        "recall": float(recall_score(target, predicted, zero_division=0)),
        "f1": float(f1_score(target, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(target, probabilities)),
        "average_precision": float(average_precision_score(target, probabilities)),
        "brier_score": float(brier_score_loss(target, probabilities)),
        "log_loss": float(log_loss(target, probabilities, labels=[0, 1])),
        "confusion_matrix": confusion_matrix(target, predicted, labels=[0, 1]).tolist(),
    }


def train_and_evaluate(dataset, model_path, report_path, seed=42):
    dataset, model_path, report_path = map(Path, (dataset, model_path, report_path))
    frame = pd.read_csv(dataset)
    if frame["recovered"].isna().any() or set(frame["recovered"].unique()) != {0, 1}:
        raise ValueError("The recovered target must contain only 0 and 1")
    train, test = split_contexts(frame, seed)
    train_x, test_x = prepare_features(train), prepare_features(test)
    model = build_model(seed).fit(train_x, train["recovered"])
    probabilities = model.predict_proba(test_x)[:, 1]
    baseline = DummyClassifier(strategy="prior").fit(train_x, train["recovered"])
    baseline_probabilities = baseline.predict_proba(test_x)[:, 1]
    observed, predicted = calibration_curve(test["recovered"], probabilities, n_bins=10, strategy="uniform")
    train_groups, test_groups = set(train["customer_id"]), set(test["customer_id"])
    report = {
        "data_scope": "synthetic_only; no production accuracy or revenue-uplift claim",
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "sklearn_version": sklearn.__version__,
        "split": {
            "method": "GroupShuffleSplit", "group_column": "customer_id", "seed": seed,
            "train_rows": len(train), "test_rows": len(test),
            "train_contexts": len(train_groups), "test_contexts": len(test_groups),
            "overlapping_contexts": len(train_groups & test_groups),
            "train_positive_rate": float(train["recovered"].mean()),
            "test_positive_rate": float(test["recovered"].mean()),
        },
        "classification_threshold": 0.5,
        "threshold_policy": "Fixed in advance; test set is not used for threshold selection",
        "model": evaluate_probabilities(test["recovered"], probabilities),
        "training_prior_baseline": evaluate_probabilities(test["recovered"], baseline_probabilities),
        "calibration_bins": [
            {"mean_predicted_probability": float(p), "observed_recovery_fraction": float(y)}
            for p, y in zip(predicted, observed)
        ],
        "limitations": [
            "Synthetic outcomes do not validate real merchant performance.",
            "Calibration bins are diagnostic; the model has not been recalibrated.",
            "The saved estimator is fitted on the training partition only.",
            "Existing dashboard revenue simulations are not this held-out ML evaluation.",
        ],
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    report["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/synthetic_payments.csv")
    parser.add_argument("--model", type=Path, default=ROOT / "ML/recovery_model.joblib")
    parser.add_argument("--report", type=Path, default=ROOT / "ML/evaluation.json")
    args = parser.parse_args()
    report = train_and_evaluate(args.dataset, args.model, args.report)
    print(json.dumps({"split": report["split"], "model": report["model"],
                      "baseline": report["training_prior_baseline"]}, indent=2))
    print(f"Saved model: {args.model}\nSaved report: {args.report}")


if __name__ == "__main__":
    main()
