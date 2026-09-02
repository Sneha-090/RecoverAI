import os
import numpy as np
import pandas as pd

# Reproducibility ke liye
np.random.seed(42)

# Number of synthetic records
N = 2000

# -----------------------------
# 1. Generate basic features
# -----------------------------

amount = np.random.lognormal(mean=6.5, sigma=0.8, size=N)
amount = np.clip(amount, 100, 10000).round(2)

# IMPORTANT: these MUST match the cause strings returned by
# app/services/diagnosis.py's diagnose() function, otherwise the
# trained model will never have seen the real cause categories it
# gets fed at inference time (Day 3).
causes = [
    "network_error",
    "insufficient_funds",
    "bank_declined",
    "card_declined"
]

cause = np.random.choice(
    causes,
    size=N,
    p=[0.30, 0.30, 0.25, 0.15]
)

attempts = np.random.randint(0, 4, size=N)

# NEW: days since failure - required feature per spec Section 6.
# Recovery window is 14 days (Rules.md), so keep this bounded there.
days_since_failure = np.random.randint(0, 15, size=N)

past_rate = np.random.beta(4, 3, size=N)

# NOTE: fraud is a deterministic stopping rule (spec Section 13), not
# an ML training feature - removed from this dataset intentionally.

# MUST match the 3 candidate actions defined in spec Section 8 /
# Rules.md exactly.
actions = [
    "retry",
    "payment_link",
    "alt_method"
]

action_type = np.random.choice(
    actions,
    size=N,
    p=[0.40, 0.30, 0.30]
)


# ------------------------------------
# 2. Calculate recovery probability
# ------------------------------------

logit = np.full(N, -0.7)

logit += 2.0 * (past_rate - 0.5)
logit -= 0.45 * attempts

# NEW: recovery gets a bit less likely the longer it's been sitting unresolved
logit -= 0.03 * days_since_failure


# ------------------------------------
# 3. Cause effects
# ------------------------------------

logit += np.where(cause == "network_error", 0.4, 0)
logit += np.where(cause == "insufficient_funds", -0.3, 0)
logit += np.where(cause == "bank_declined", -0.5, 0)
logit += np.where(cause == "card_declined", -0.2, 0)


# ------------------------------------
# 4. Action effects
# ------------------------------------

# Retry works relatively well for network errors
logit += np.where(
    (cause == "network_error") & (action_type == "retry"),
    0.8,
    0
)

# Payment link can help with card-declined cases
logit += np.where(
    (cause == "card_declined") & (action_type == "payment_link"),
    0.7,
    0
)

# Alt-method nudge helps with insufficient funds (e.g. suggest UPI instead)
logit += np.where(
    (cause == "insufficient_funds") & (action_type == "alt_method"),
    0.5,
    0
)

# Retry is less useful after a bank decline
logit += np.where(
    (cause == "bank_declined") & (action_type == "retry"),
    -0.6,
    0
)


# ------------------------------------
# 5. Add realistic randomness
# ------------------------------------

noise = np.random.normal(loc=0, scale=0.5, size=N)
logit += noise


# ------------------------------------
# 6. Convert logit -> probability
# ------------------------------------

recovery_probability = 1 / (1 + np.exp(-logit))


# ------------------------------------
# 7. Generate final outcome
# ------------------------------------

recovered = np.random.binomial(1, recovery_probability)


# ------------------------------------
# 8. Create DataFrame
# ------------------------------------

df = pd.DataFrame({
    "customer_id": [f"CUST_{i:05d}" for i in range(1, N + 1)],
    "amount": amount,
    "cause": cause,
    "attempts": attempts,
    "days_since_failure": days_since_failure,
    "past_rate": past_rate.round(3),
    "action_type": action_type,
    "recovered": recovered
})


# ------------------------------------
# 9. Save CSV
# ------------------------------------

output_path = "data/synthetic_payments.csv"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
df.to_csv(output_path, index=False)

print(f"Generated {len(df)} synthetic payment records.")
print(f"Saved to: {output_path}")

print("\nFirst 5 rows:")
print(df.head())

print("\nRecovery distribution:")
print(df["recovered"].value_counts())

print("\nOverall recovery rate:")
print(df["recovered"].mean())

print("\nRecovery rate by cause:")
print(df.groupby("cause")["recovered"].mean().round(3))

print("\nRecovery rate by action_type:")
print(df.groupby("action_type")["recovered"].mean().round(3))

print("\nRecovery rate by (cause, action_type):")
print(df.groupby(["cause", "action_type"])["recovered"].mean().round(3))

print("\nAction_type class balance (counts):")
print(df["action_type"].value_counts())

print("\nCause class balance (counts):")
print(df["cause"].value_counts())