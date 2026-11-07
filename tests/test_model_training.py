import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from ML.train_model import prepare_features, split_contexts, train_and_evaluate


DATASET = Path(__file__).resolve().parents[1] / "data/synthetic_payments.csv"


def test_every_customer_context_stays_on_one_side_of_split():
    frame = pd.read_csv(DATASET)
    train, test = split_contexts(frame)
    assert not set(train.customer_id) & set(test.customer_id)
    assert len(train) + len(test) == len(frame)
    assert train.groupby("customer_id").action_type.nunique().eq(3).all()
    assert test.groupby("customer_id").action_type.nunique().eq(3).all()
    assert train.customer_id.nunique() == 1600
    assert test.customer_id.nunique() == 400


def test_split_is_reproducible():
    frame = pd.read_csv(DATASET)
    a, b = split_contexts(frame)
    c, d = split_contexts(frame)
    assert a.index.equals(c.index)
    assert b.index.equals(d.index)


def test_customer_identity_and_target_are_not_model_features():
    frame = pd.read_csv(DATASET).head(3)
    features = prepare_features(frame)
    assert "customer_id" not in features
    assert "recovered" not in features
    assert features["cause_action"].equals(frame.cause + "__" + frame.action_type)


def test_training_produces_reloadable_model_and_verifiable_report(tmp_path):
    model_path, report_path = tmp_path / "model.joblib", tmp_path / "evaluation.json"
    report = train_and_evaluate(DATASET, model_path, report_path)
    assert json.loads(report_path.read_text()) == report
    assert report["split"]["overlapping_contexts"] == 0
    assert report["model_sha256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert report["dataset_sha256"] == hashlib.sha256(DATASET.read_bytes()).hexdigest()
    frame = pd.read_csv(DATASET)
    _, test = split_contexts(frame)
    predictions = joblib.load(model_path).predict_proba(prepare_features(test))[:, 1]
    assert np.isfinite(predictions).all()
    assert ((predictions >= 0) & (predictions <= 1)).all()
    assert sum(map(sum, report["model"]["confusion_matrix"])) == len(test)
    assert report["classification_threshold"] == 0.5
    assert 0 <= report["training_prior_baseline"]["brier_score"] <= 1
    assert report["model"]["brier_score"] < report["training_prior_baseline"]["brier_score"]


def test_unknown_failure_cause_still_has_finite_predictions(tmp_path):
    path = tmp_path / "model.joblib"
    train_and_evaluate(DATASET, path, tmp_path / "report.json")
    frame = pd.read_csv(DATASET).head(3)
    frame["cause"] = "previously_unseen_cause"
    assert np.isfinite(joblib.load(path).predict_proba(prepare_features(frame))).all()


@pytest.mark.parametrize("bad_groups", [[None, "B"], ["A", "A"]])
def test_missing_or_single_customer_group_is_rejected(bad_groups):
    with pytest.raises(ValueError, match="groups"):
        split_contexts(pd.DataFrame({"customer_id": bad_groups, "recovered": [0, 1]}))



def test_inner_selection_and_feature_support_do_not_include_outer_test(tmp_path):
    report = train_and_evaluate(DATASET,tmp_path/'model.joblib',tmp_path/'report.json')
    selection=report['model_selection']
    assert selection['outer_test_used_for_selection'] is False
    assert selection['overlapping_contexts']==0
    assert selection['fit_contexts']+selection['validation_contexts']==report['split']['train_contexts']
    best=min(selection['candidates'],key=lambda row:(row['log_loss'],row['brier_score'],row['name']))
    assert selection['selected_candidate']==best['name']
    frame=pd.read_csv(DATASET);train,_=split_contexts(frame)
    assert report['feature_support']['amount']=={'min':float(train.amount.min()),'max':float(train.amount.max())}
    assert sum(row['action_rows'] for row in report['calibration_bins'])==report['split']['test_rows']
    assert set(report['per_action'])=={'retry','payment_link','alt_method'}
