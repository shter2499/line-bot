"""
evaluate_classifier.py
----------------------
ใช้ประเมิน classifier ที่ train แล้วบน test set ที่กำหนดเอง
รองรับ 2 โหมด:
  1) ใช้ CSV เดิม (data.csv) แล้วแบ่ง test set ด้วย seed เดียวกับตอน train
  2) ระบุ CSV test set แยกต่างหาก ด้วย --test-csv path/to/test.csv

Usage:
  python evaluate_classifier.py
  python evaluate_classifier.py --test-csv my_test.csv
  python evaluate_classifier.py --model-dir classifier-edc --train-csv data.csv
"""
from __future__ import annotations
import argparse
import json
import os
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    ConfusionMatrixDisplay,
    f1_score,
    precision_score,
    recall_score,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_model(model_dir: str):
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    import torch
    # Convert to absolute path to avoid HuggingFace validation error
    model_dir = os.path.abspath(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir, local_files_only=True)
    model.eval()
    mapping_path = os.path.join(model_dir, "label_mapping.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            mp = json.load(f)
        id2label = {int(k): v for k, v in mp.get("id2label", {}).items()}
    else:
        id2label = {i: model.config.id2label[i] for i in range(model.config.num_labels)}
    return tokenizer, model, id2label


def predict_batch(texts: list[str], tokenizer, model, id2label: dict) -> tuple[list[str], list[dict]]:
    import torch
    import torch.nn.functional as F
    preds = []
    probs_list = []
    for text in texts:
        inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=192)
        with torch.no_grad():
            logits = model(**inputs).logits
            probs = F.softmax(logits, dim=-1)[0]
            pred_id = int(logits.argmax(dim=-1).item())
        preds.append(id2label[pred_id])
        probs_list.append({id2label[i]: float(probs[i]) for i in range(len(id2label))})
    return preds, probs_list


def get_test_data(test_csv: str | None, train_csv: str, test_size: float, seed: int):
    """Load test data — either from a separate CSV or by splitting the training CSV."""
    from datasets import load_dataset, Dataset

    def _find_col(column_names, possible):
        lower_map = {c.lower(): c for c in column_names}
        for p in possible:
            if p in lower_map:
                return lower_map[p]
        return None

    if test_csv:
        raw = load_dataset("csv", data_files=test_csv, split="train")
    else:
        raw = load_dataset("csv", data_files=train_csv, split="train")

    text_col = _find_col(raw.column_names, ["text", "input", "message"])
    key_col = _find_col(raw.column_names, ["key", "label"])

    if text_col is None or key_col is None:
        raise ValueError(f"ไม่พบ column ที่ต้องการ (text/input/message และ key/label). Columns: {raw.column_names}")

    valid = raw.filter(lambda ex: isinstance(ex[text_col], str) and ex[text_col].strip()
                       and isinstance(ex[key_col], str) and ex[key_col].strip())

    texts = valid[text_col]
    labels_raw = [" ".join(str(v).strip().lower().split()) for v in valid[key_col]]
    labels = ["edc" if "edc" in v else "other" for v in labels_raw]

    if test_csv:
        return texts, labels

    # Split same way as training
    from datasets import Dataset as HFDataset
    ds = HFDataset.from_dict({"text": texts, "label": labels})
    splits = ds.train_test_split(test_size=test_size, seed=seed)
    return splits["test"]["text"], splits["test"]["label"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default="line-bot/classifier-edc")
    parser.add_argument("--train-csv", default="line-bot/data.csv")
    parser.add_argument("--test-csv", default=None, help="CSV test set แยกต่างหาก (ถ้าไม่ระบุจะแบ่งจาก train-csv)")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    # parser.add_argument("--output-dir", default="line-bot", help="โฟลเดอร์สำหรับบันทึก confusion_matrix.png")
    args = parser.parse_args()

    print(f"Loading model from: {args.model_dir}")
    tokenizer, model, id2label = load_model(args.model_dir)
    label_names = [id2label[i] for i in sorted(id2label)]

    print("Loading test data...")
    texts, y_true = get_test_data(
        test_csv=args.test_csv,
        train_csv=args.train_csv,
        test_size=args.test_size,
        seed=args.seed,
    )
    print(f"Test samples: {len(texts)}")

    print("Running predictions...")
    y_pred, y_probs = predict_batch(list(texts), tokenizer, model, id2label)

    # --- 1) Accuracy ---
    acc = accuracy_score(y_true, y_pred)
    print(f"\n=== Accuracy: {acc:.4f} ===")

    # --- 2) F1 / Precision / Recall ---
    f1 = f1_score(y_true, y_pred, average="macro", zero_division=0)
    precision = precision_score(y_true, y_pred, average="macro", zero_division=0)
    recall = recall_score(y_true, y_pred, average="macro", zero_division=0)
    print(f"F1 (macro):  {f1:.4f}")
    print(f"Precision:   {precision:.4f}")
    print(f"Recall:      {recall:.4f}")

    # --- 3) Classification report ---
    print("\n=== Classification Report ===")
    print(classification_report(y_true, y_pred, labels=label_names, zero_division=0))

    # --- 4) Confusion matrix ---
    cm = confusion_matrix(y_true, y_pred, labels=label_names)
    disp = ConfusionMatrixDisplay(confusion_matrix=cm, display_labels=label_names)
    disp.plot(colorbar=False)
    plt.title("Confusion Matrix")
    plt.tight_layout()
    # out_path = os.path.join(args.output_dir, "confusion_matrix.png")
    # plt.savefig(out_path)
    # print(f"\nConfusion matrix saved to: {out_path}")

    # --- 5) Error analysis JSON ---
    error_records = []
    for idx, (text, true_label, pred_label, probs) in enumerate(zip(texts, y_true, y_pred, y_probs)):
        confidence = max(probs.values())
        error_records.append({
            "index": idx,
            "text": text,
            "true_label": true_label,
            "predicted_label": pred_label,
            "is_correct": true_label == pred_label,
            "confidence": confidence,
            "probabilities": probs,
        })
    # error_path = os.path.join(args.output_dir, "error_analysis.json")
    # with open(error_path, "w", encoding="utf-8") as f:
    #     json.dump(error_records, f, ensure_ascii=False, indent=2)
    # print(f"Error analysis saved to: {error_path}")

    # --- 6) Metrics summary JSON ---
    metrics = {
        "accuracy": acc,
        "f1_macro": f1,
        "precision_macro": precision,
        "recall_macro": recall,
        "num_samples": len(texts),
        "num_errors": sum(1 for r in error_records if not r["is_correct"]),
        "model_dir": args.model_dir,
    }
    # metrics_path = os.path.join(args.output_dir, "metrics.json")
    # with open(metrics_path, "w", encoding="utf-8") as f:
    #     json.dump(metrics, f, ensure_ascii=False, indent=2)
    # print(f"Metrics saved to: {metrics_path}")


if __name__ == "__main__":
    main()
