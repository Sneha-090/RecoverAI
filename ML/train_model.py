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
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
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


def build_model(seed=42, candidate="logistic_c1"):
    classifiers = {
        "logistic_c01": LogisticRegression(C=.1, max_iter=1000, random_state=seed),
        "logistic_c1": LogisticRegression(C=1, max_iter=1000, random_state=seed),
        "logistic_c10": LogisticRegression(C=10, max_iter=1000, random_state=seed),
        "random_forest": RandomForestClassifier(n_estimators=100, min_samples_leaf=20, random_state=seed, n_jobs=1),
    }
    return Pipeline([
        ("preprocessor", ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("numerical", StandardScaler(), NUMERICAL),
        ])),
        ("classifier", classifiers[candidate]),
    ])


def evaluate_probabilities(target, probabilities):
    predicted = np.asarray(probabilities) >= 0.5
    return {
        "accuracy": float(accuracy_score(target, predicted)),
        "precision": float(precision_score(target, predicted, zero_division=0)),
        "recall": float(recall_score(target, predicted, zero_division=0)),
        "f1": float(f1_score(target, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(target, probabilities)) if len(np.unique(target)) == 2 else None,
        "average_precision": float(average_precision_score(target, probabilities)),
        "brier_score": float(brier_score_loss(target, probabilities)),
        "log_loss": float(log_loss(target, probabilities, labels=[0, 1])),
        "confusion_matrix": confusion_matrix(target, predicted, labels=[0, 1]).tolist(),
    }



def fit_selected_model(train, seed=42):
    """Select using inner validation groups only; outer test is never an input."""
    fit, validation = split_contexts(train, seed+1000)
    candidates = []
    for name in ('logistic_c01','logistic_c1','logistic_c10','random_forest'):
        candidate = build_model(seed, name).fit(prepare_features(fit), fit['recovered'])
        probabilities = candidate.predict_proba(prepare_features(validation))[:,1]
        candidates.append({'name':name,
            'log_loss':float(log_loss(validation['recovered'], probabilities, labels=[0,1])),
            'brier_score':float(brier_score_loss(validation['recovered'], probabilities))})
    winner = min(candidates, key=lambda row:(row['log_loss'],row['brier_score'],row['name']))['name']
    model = build_model(seed,winner).fit(prepare_features(train),train['recovered'])
    model.supported_ranges_ = {name:{'min':float(train[name].min()),'max':float(train[name].max())}
                               for name in NUMERICAL}
    model.selected_candidate_ = winner
    selection = {'method':'inner GroupShuffleSplit; validation log loss, then Brier, then stable name',
        'seed':seed+1000, 'fit_contexts':fit.customer_id.nunique(),
        'validation_contexts':validation.customer_id.nunique(),
        'overlapping_contexts':len(set(fit.customer_id)&set(validation.customer_id)),
        'selected_candidate':winner,'candidates':candidates,
        'outer_test_used_for_selection':False}
    return model, selection


def calibration_bins(target, probabilities):
    target, probabilities = np.asarray(target),np.asarray(probabilities)
    bins = np.minimum((probabilities*10).astype(int),9)
    return [{'mean_predicted_probability':float(probabilities[bins==index].mean()),
             'observed_recovery_fraction':float(target[bins==index].mean()),
             'action_rows':int((bins==index).sum())}
            for index in range(10) if (bins==index).any()]


def train_and_evaluate(dataset, model_path, report_path, seed=42):
    dataset, model_path, report_path = map(Path, (dataset, model_path, report_path))
    frame = pd.read_csv(dataset)
    if frame["recovered"].isna().any() or set(frame["recovered"].unique()) != {0, 1}:
        raise ValueError("The recovered target must contain only 0 and 1")
    train, test = split_contexts(frame, seed)
    train_x, test_x = prepare_features(train), prepare_features(test)
    model, selection = fit_selected_model(train, seed)
    probabilities = model.predict_proba(test_x)[:, 1]
    baseline = DummyClassifier(strategy="prior").fit(train_x, train["recovered"])
    baseline_probabilities = baseline.predict_proba(test_x)[:, 1]
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
        "model_selection": selection,
        "feature_support": model.supported_ranges_,
        "per_action": {action:evaluate_probabilities(test.loc[test.action_type==action,'recovered'],
                       probabilities[test.action_type.to_numpy()==action]) for action in sorted(test.action_type.unique())},
        "per_cause": {cause:evaluate_probabilities(test.loc[test.cause==cause,'recovered'],
                      probabilities[test.cause.to_numpy()==cause]) for cause in sorted(test.cause.unique())},
        "calibration_bins": calibration_bins(test['recovered'], probabilities),
        "limitations": [
            "Synthetic outcomes do not validate real merchant performance.",
            "This existing synthetic test set has prior project evaluations; it is not a fresh blind merchant audit.",
            "Candidate selection uses one inner grouped split; selection stability and real data validation remain necessary.",
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
