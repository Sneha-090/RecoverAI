import joblib
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report
)


import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression

df = pd.read_csv("data/synthetic_payments.csv")

print("Dataset shape:", df.shape)
print("\nColumns:")
print(df.columns.tolist())

print("\nFirst 5 rows:")
print(df.head())

# -----------------------------
# Separate features and target
# -----------------------------

X = df.drop(columns=["customer_id", "recovered"])
y = df["recovered"]

print("\nFeature columns:")
print(X.columns.tolist())

print("\nTarget:")
print(y.name)

print("\nFeature shape:", X.shape)
print("Target shape:", y.shape)
# -----------------------------
# Train / Test Split
# -----------------------------

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.20,
    random_state=42,
    stratify=y
)

print("\nTraining data:")
print("X_train:", X_train.shape)
print("y_train:", y_train.shape)

print("\nTesting data:")
print("X_test:", X_test.shape)
print("y_test:", y_test.shape)
# -----------------------------
# Define categorical & numerical columns
# -----------------------------

categorical_features = [
    "cause",
    "action_type"
]

numerical_features = [
    "amount",
    "attempts",
    "days_since_failure",
    "past_rate"
]

# -----------------------------
# One-Hot Encoding
# -----------------------------

preprocessor = ColumnTransformer(
    transformers=[
        (
            "categorical",
            OneHotEncoder(handle_unknown="ignore"),
            categorical_features
        ),
        (
            "numerical",
              StandardScaler(),
            numerical_features
        )
    ]
)

print("\nCategorical features:")
print(categorical_features)

print("\nNumerical features:")
print(numerical_features)

print("\nPreprocessor created successfully.")
# -----------------------------
# Create Logistic Regression pipeline
# -----------------------------
model = Pipeline(
    steps=[
        ("preprocessor", preprocessor),
        ("classifier", LogisticRegression(
            max_iter=1000,
            random_state=42
        ))
    ]
)

print("\nLogistic Regression pipeline created.")
# -----------------------------
# Train the model
# -----------------------------

model.fit(X_train, y_train)

print("Model training completed.")

# -----------------------------
# Save trained model
# -----------------------------

model_path = "ML/recovery_model.joblib"

joblib.dump(model, model_path)

print(f"Model saved to: {model_path}")
# -----------------------------
# Make predictions on test data
# -----------------------------

y_pred = model.predict(X_test)

y_probability = model.predict_proba(X_test)[:, 1]

print("\nFirst 10 predictions:")
print(y_pred[:10])

print("\nFirst 10 recovery probabilities:")
print(y_probability[:10])

# -----------------------------
# Evaluate the model
# -----------------------------

accuracy = accuracy_score(y_test, y_pred)
precision = precision_score(y_test, y_pred)
recall = recall_score(y_test, y_pred)
f1 = f1_score(y_test, y_pred)

print("\nModel Performance:")
print("Accuracy :", round(accuracy, 3))
print("Precision:", round(precision, 3))
print("Recall   :", round(recall, 3))
print("F1 Score :", round(f1, 3))

print("\nConfusion Matrix:")
print(confusion_matrix(y_test, y_pred))

print("\nClassification Report:")
print(classification_report(y_test, y_pred))

print("\nProbability statistics:")
print(pd.Series(y_probability).describe())

print("\nNumber of predictions above thresholds:")

for threshold in [0.3, 0.4, 0.5, 0.6, 0.7]:
    count = (y_probability >= threshold).sum()
    print(f"Threshold {threshold}: {count} cases")

print("\nThreshold Analysis:")

for threshold in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
    threshold_pred = (y_probability >= threshold).astype(int)

    precision_t = precision_score(y_test, threshold_pred, zero_division=0)
    recall_t = recall_score(y_test, threshold_pred, zero_division=0)
    f1_t = f1_score(y_test, threshold_pred, zero_division=0)

    print(
        f"Threshold {threshold:.2f} | "
        f"Precision: {precision_t:.3f} | "
        f"Recall: {recall_t:.3f} | "
        f"F1: {f1_t:.3f}"
    )