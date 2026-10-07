import pandas as pd
import numpy as np
import pickle
import os
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, accuracy_score

print("Loading real SWGDRUG mass spectral features...")
df = pd.read_csv("swgdrug_features.csv")

# Feature columns (mz_10 to mz_550)
feature_cols = [c for c in df.columns if c.startswith("mz_")]
X = df[feature_cols].values
y = df['Category'].values

print(f"Dataset shape: {X.shape}, Target classes: {np.unique(y)}")

# Split data
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

print(f"Training Random Forest Classifier on {X_train.shape[0]} samples...")
model = RandomForestClassifier(n_estimators=150, max_depth=20, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
acc = accuracy_score(y_test, y_pred)
print(f"\n--- Model Performance on Real SWGDRUG Test Data ---")
print(f"Accuracy: {acc:.4f} ({acc*100:.2f}%)")
print("\nClassification Report:")
print(classification_report(y_test, y_pred, zero_division=0))

# Save artifacts
with open("model.pkl", "wb") as f:
    pickle.dump(model, f)

with open("features.pkl", "wb") as f:
    pickle.dump(feature_cols, f)

print("Saved model.pkl and features.pkl successfully!")
