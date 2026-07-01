"""
analyze_errors.py
-----------------
วิเคราะห์ข้อความที่ classifier ทายผิดจาก test set
แสดงรายละเอียดว่าข้อความไหนทาย label ผิด และผิดยังไง

Usage:
    python analyze_errors.py
    python analyze_errors.py --model-dir ./classifier-edc --output error_analysis.csv
"""
from __future__ import annotations
import argparse
import json
import os
import pandas as pd
import numpy as np
from datasets import load_dataset, Dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch


def load_classifier(model_dir: str):
    """Load trained classifier from directory"""
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    model.eval()
    
    mapping_path = os.path.join(model_dir, "label_mapping.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, "r", encoding="utf-8") as f:
            mp = json.load(f)
        id2label = {int(k): v for k, v in mp.get("id2label", {}).items()}
    else:
        id2label = {i: model.config.id2label[i] for i in range(model.config.num_labels)}
    
    return tokenizer, model, id2label


def predict_text(text: str, tokenizer, model, id2label: dict) -> tuple[str, dict]:
    """Predict single text and return label + probabilities"""
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding=True, max_length=192)
    with torch.no_grad():
        logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
    pred_id = int(np.argmax(probs))
    prob_dict = {id2label[i]: float(probs[i]) for i in range(len(probs))}
    return id2label[pred_id], prob_dict


def load_test_data(csv_path: str, test_size: float = 0.2, seed: int = 42):
    """Load and split data exactly the same way as train_classifier.py"""
    from typing import Dict, List
    
    raw_dataset = load_dataset("csv", data_files=csv_path, split="train")
    
    def _norm(raw_value: str | None) -> str | None:
        if raw_value is None:
            return None
        return " ".join(str(raw_value).strip().lower().split()) or None
    
    def _find_col(possible: List[str]) -> str | None:
        lowercase_to_original = {col_name.lower(): col_name for col_name in raw_dataset.column_names}
        for candidate in possible:
            if candidate in lowercase_to_original:
                return lowercase_to_original[candidate]
        return None
    
    text_column_name = _find_col(["text", "input", "message"])
    label_column_name = _find_col(["key", "label"])
    
    if text_column_name is None or label_column_name is None:
        raise ValueError(f"CSV must contain text and label columns. Found: {raw_dataset.column_names}")
    
    def _is_valid_row(ex: Dict) -> bool:
        text_value = ex.get(text_column_name)
        label_value = ex.get(label_column_name)
        return isinstance(text_value, str) and text_value.strip() and isinstance(label_value, str) and label_value.strip()
    
    filtered_dataset = raw_dataset.filter(_is_valid_row)
    
    # Normalize labels to binary (same as training)
    raw_label_values = [_norm(v) for v in filtered_dataset[label_column_name]]
    normalized_labels = ["edc" if (v and "edc" in v) else "other" for v in raw_label_values]
    
    text_samples = filtered_dataset[text_column_name]
    full_dataset = Dataset.from_dict({"text": text_samples, "label": normalized_labels})
    
    # Split with same seed as training
    splits = full_dataset.train_test_split(test_size=test_size, seed=seed)
    test_dataset = splits["test"]
    
    return test_dataset["text"], test_dataset["label"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default="./classifier-edc", help="Path to saved model")
    parser.add_argument("--csv-path", default="data.csv", help="Path to original CSV data")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split size (must match training)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (must match training)")
    parser.add_argument("--output", default="error_analysis.csv", help="Output CSV file for errors")
    parser.add_argument("--show-all", action="store_true", help="Show all predictions, not just errors")
    args = parser.parse_args()
    
    print(f"Loading model from: {args.model_dir}")
    tokenizer, model, id2label = load_classifier(args.model_dir)
    
    print(f"Loading test data from: {args.csv_path}")
    test_texts, test_labels = load_test_data(args.csv_path, args.test_size, args.seed)
    print(f"Test samples: {len(test_texts)}")
    
    print("\nRunning predictions...")
    results = []
    correct_count = 0
    error_count = 0
    
    for i, (text, true_label) in enumerate(zip(test_texts, test_labels)):
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(test_texts)}...")
        
        pred_label, probs = predict_text(text, tokenizer, model, id2label)
        is_correct = pred_label == true_label
        
        if is_correct:
            correct_count += 1
        else:
            error_count += 1
        
        # Collect result
        result = {
            "index": i,
            "text": text,
            "true_label": true_label,
            "predicted_label": pred_label,
            "is_correct": is_correct,
            "confidence": probs[pred_label],
            "prob_other": probs.get("other", 0.0),
            "prob_edc": probs.get("edc", 0.0),
        }
        
        if args.show_all or not is_correct:
            results.append(result)
    
    # Print summary
    accuracy = correct_count / len(test_texts)
    print(f"\n{'='*60}")
    print(f"Total predictions: {len(test_texts)}")
    print(f"Correct: {correct_count} ({accuracy:.2%})")
    print(f"Errors: {error_count} ({1-accuracy:.2%})")
    print(f"{'='*60}")
    
    # Save to CSV
    df = pd.DataFrame(results)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\nResults saved to: {args.output}")
    print(f"Total rows in output: {len(df)}")
    
    # Show error breakdown
    if not args.show_all and error_count > 0:
        print(f"\n{'='*60}")
        print("Error Breakdown:")
        print(f"{'='*60}")
        
        false_positives = df[(df["true_label"] == "other") & (df["predicted_label"] == "edc")]
        false_negatives = df[(df["true_label"] == "edc") & (df["predicted_label"] == "other")]
        
        print(f"False Positives (predicted EDC, actually OTHER): {len(false_positives)}")
        print(f"False Negatives (predicted OTHER, actually EDC): {len(false_negatives)}")
        
        if len(false_negatives) > 0:
            print(f"\nSample False Negatives (missed EDC cases):")
            for idx, row in false_negatives.head(5).iterrows():
                print(f"  [{row['index']}] {row['text'][:80]}... (confidence: {row['confidence']:.2%})")
        
        if len(false_positives) > 0:
            print(f"\nSample False Positives (wrongly flagged as EDC):")
            for idx, row in false_positives.head(5).iterrows():
                print(f"  [{row['index']}] {row['text'][:80]}... (confidence: {row['confidence']:.2%})")


if __name__ == "__main__":
    main()
