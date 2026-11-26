"""
Publish a trained model to the MLflow registry so SolanumAI can serve it.

    MLFLOW_TRACKING_URI=http://localhost:5000 uv run --package solanumai \
        python scripts/publish_model.py --key oa --model path/to/model.joblib --sample path/to/sample.csv

What it does:
1. logs the fitted pipeline in a run (sklearn flavour) and registers a new version under <key>;
2. attaches the SHAP background sample as run artifact explainer/sample.csv;
3. points the alias (default: champion) at the new version -> SolanumAI loads it at its next start.
"""

import argparse

import joblib
import mlflow
import mlflow.sklearn
from mlflow import MlflowClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--key", required=True, help="registry key = registered model name, e.g. oa"
    )
    parser.add_argument(
        "--model", required=True, help="fitted scikit-learn pipeline (.joblib)"
    )
    parser.add_argument(
        "--sample", required=True, help="SHAP background sample (.csv, raw features)"
    )
    parser.add_argument("--alias", default="champion")
    args = parser.parse_args()

    pipeline = joblib.load(args.model)
    mlflow.set_experiment(f"solanumai-{args.key}")

    with mlflow.start_run(run_name=f"publish-{args.key}") as run:
        # MLflow 3: name=...   (MLflow 2: artifact_path="model")
        info = mlflow.sklearn.log_model(
            pipeline, name="model", registered_model_name=args.key
        )
        mlflow.log_artifact(args.sample, artifact_path="explainer")

    version = info.registered_model_version
    MlflowClient().set_registered_model_alias(args.key, args.alias, str(version))
    print(f"Registered {args.key} v{version} as @{args.alias} (run {run.info.run_id})")


if __name__ == "__main__":
    main()
