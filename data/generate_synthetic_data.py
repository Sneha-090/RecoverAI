import os

import numpy as np
import pandas as pd


# ------------------------------------
# Reproducibility
# ------------------------------------

np.random.seed(42)


# ------------------------------------
# Number of payment contexts
# ------------------------------------

N = 2000


# ------------------------------------
# 1. Generate one base context per payment
# ------------------------------------

customer_ids = [f"CUST_{i:05d}" for i in range(1, N + 1)]

amount = np.random.lognormal(
    mean=6.5,
    sigma=0.8,
    size=N
)

amount = np.clip(
    amount,
    100,
    10000
).round(2)


# Must match diagnosis.py
causes = [
    "network_error",
    "insufficient_funds",
    "bank_declined",
    "card_declined",
]

cause = np.random.choice(
    causes,
    size=N,
    p=[0.30, 0.30, 0.25, 0.15],
)


# Number of attempts already made before this recovery decision
attempts = np.random.randint(
    0,
    4,
    size=N,
)


# Recovery window is 14 days
days_since_failure = np.random.randint(
    0,
    15,
    size=N,
)


# ------------------------------------
# 2. Simulate customer history
# ------------------------------------

previous_failures = np.random.randint(
    1,
    8,
    size=N,
)

true_customer_recovery_rate = np.random.beta(
    5,
    3,
    size=N,
)

previous_recoveries = np.random.binomial(
    previous_failures,
    true_customer_recovery_rate,
)

past_rate = (
    previous_recoveries / previous_failures
)


# ------------------------------------
# 3. Create all candidate actions
# ------------------------------------

actions = [
    "retry",
    "payment_link",
    "alt_method",
]

# Every payment context gets all 3 actions.
action_type = np.tile(
    actions,
    N,
)


# Repeat each context three times:
# one row for retry,
# one row for payment_link,
# one row for alt_method.

customer_id = np.repeat(
    customer_ids,
    3,
)

amount = np.repeat(
    amount,
    3,
)

cause = np.repeat(
    cause,
    3,
)

attempts = np.repeat(
    attempts,
    3,
)

days_since_failure = np.repeat(
    days_since_failure,
    3,
)

past_rate = np.repeat(
    past_rate,
    3,
)


# ------------------------------------
# 4. Calculate recovery probability
# ------------------------------------

logit = np.full(
    len(customer_id),
    -0.7,
)


# Customer history
logit += 2.0 * (
    past_rate - 0.5
)


# More previous attempts → diminishing recovery probability
logit -= 0.45 * attempts


# Older failed payments become harder to recover
logit -= 0.03 * days_since_failure


# ------------------------------------
# 5. Cause effects
# ------------------------------------

logit += np.where(
    cause == "network_error",
    0.4,
    0,
)

logit += np.where(
    cause == "insufficient_funds",
    -0.3,
    0,
)

logit += np.where(
    cause == "bank_declined",
    -0.5,
    0,
)

logit += np.where(
    cause == "card_declined",
    -0.2,
    0,
)


# ------------------------------------
# 6. Cause × Action effects
# ------------------------------------

# Retry is particularly useful for transient network failures.
logit += np.where(
    (cause == "network_error")
    & (action_type == "retry"),
    0.8,
    0,
)


# Payment link is useful when the card itself may be the issue.
logit += np.where(
    (cause == "card_declined")
    & (action_type == "payment_link"),
    0.7,
    0,
)


# Alternative payment method can help with insufficient funds.
logit += np.where(
    (cause == "insufficient_funds")
    & (action_type == "alt_method"),
    0.5,
    0,
)


# Retrying a bank-declined payment is less useful.
logit += np.where(
    (cause == "bank_declined")
    & (action_type == "retry"),
    -0.6,
    0,
)


# ------------------------------------
# 7. Add outcome randomness
# ------------------------------------

noise = np.random.normal(
    loc=0,
    scale=0.5,
    size=len(customer_id),
)

logit += noise


# ------------------------------------
# 8. Convert logit → probability
# ------------------------------------

recovery_probability = 1 / (
    1 + np.exp(-logit)
)


# ------------------------------------
# 9. Generate actual outcome
# ------------------------------------

recovered = np.random.binomial(
    1,
    recovery_probability,
)


# ------------------------------------
# 10. Create training dataframe
# ------------------------------------

df = pd.DataFrame(
    {
        "customer_id": customer_id,
        "amount": amount,
        "cause": cause,
        "attempts": attempts,
        "days_since_failure": days_since_failure,
        "past_rate": np.round(past_rate, 3),
        "action_type": action_type,
        "recovered": recovered,
    }
)


# ------------------------------------
# 11. Save CSV
# ------------------------------------

output_path = "data/synthetic_payments.csv"

os.makedirs(
    os.path.dirname(output_path),
    exist_ok=True,
)

df.to_csv(
    output_path,
    index=False,
)


# ------------------------------------
# 12. Diagnostics
# ------------------------------------

print(
    f"Generated {len(df)} synthetic action-level records."
)

print(
    f"Generated {N} payment contexts × "
    f"{len(actions)} candidate actions."
)

print(
    f"Saved to: {output_path}"
)


print("\nFirst 5 rows:")
print(df.head())


print("\nDataset shape:")
print(df.shape)


print("\nRecovery distribution:")
print(df["recovered"].value_counts())


print("\nOverall recovery rate:")
print(
    df["recovered"].mean()
)


print("\nRecovery rate by cause:")
print(
    df.groupby("cause")["recovered"]
    .mean()
    .round(3)
)


print("\nRecovery rate by action_type:")
print(
    df.groupby("action_type")["recovered"]
    .mean()
    .round(3)
)


print("\nRecovery rate by (cause, action_type):")
print(
    df.groupby(
        ["cause", "action_type"]
    )["recovered"]
    .mean()
    .round(3)
)


print("\nAction_type class balance:")
print(
    df["action_type"].value_counts()
)


print("\nCause class balance:")
print(
    df["cause"].value_counts()
)