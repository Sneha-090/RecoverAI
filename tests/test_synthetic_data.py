import pandas as pd

VALID_ACTIONS = {"retry", "payment_link", "alt_method"}
VALID_CAUSES = {
    "bank_declined", "insufficient_funds", "card_declined",
    "expired_card", "invalid_card", "authentication_failed",
    "network_error", "customer_cancelled", "unclassified_error",
}


def load_df():
    return pd.read_csv("data/synthetic_payments.csv")


def test_required_columns_present():
    df = load_df()
    required = {"amount", "cause", "attempts", "days_since_failure", "past_rate", "action_type", "recovered"}
    assert required.issubset(df.columns)


def test_action_types_match_spec():
    df = load_df()
    assert set(df["action_type"].unique()).issubset(VALID_ACTIONS)


def test_causes_match_diagnosis_engine():
    df = load_df()
    assert set(df["cause"].unique()).issubset(VALID_CAUSES)


def test_class_balance_across_actions():
    df = load_df()
    counts = df["action_type"].value_counts(normalize=True)
    assert (counts >= 0.15).all()


def test_no_nulls():
    df = load_df()
    assert df.isnull().sum().sum() == 0