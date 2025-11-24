from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import os
import json
import numpy as np

MODEL_DIR = "./classifier-cr"
if not os.path.isdir(MODEL_DIR):
    raise SystemExit(
        "Model directory ./classifier-cr not found. Train it first")

tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_DIR)

# Load mapping if present
mapping_path = os.path.join(MODEL_DIR, "label_mapping.json")
if os.path.exists(mapping_path):
    with open(mapping_path, "r", encoding="utf-8") as f:
        mp = json.load(f)
    id2label = {int(k): v for k, v in mp.get("id2label", {}).items()}
else:
    id2label = {i: model.config.id2label[i]
                for i in range(model.config.num_labels)}

label2id = {v: k for k, v in id2label.items()}
PROMPTPAY_FORCE_OTHER = {"พพ", "พร้อมเพย์", "promptpay"}


def classify(text: str):
    # Heuristic override: if mentions 'ปริ้นเตอร์' → force OTHER
    low = text.split('ปัญหาที่พบ:')[1].split("\n")[0] if 'ปัญหาที่พบ:' in text else text.lower()
    
    if any(tok in low for tok in PROMPTPAY_FORCE_OTHER):
        forced_label = "other" if "other" in label2id else id2label.get(
            0, "other")
        forced_id = label2id.get(forced_label, 0)
        # Return a one-hot style probability towards OTHER
        probs = np.zeros(model.config.num_labels, dtype=float)
        probs[forced_id] = 1.0
        return {
            "text": text,
            "probabilities": {id2label[i]: float(probs[i]) for i in range(len(probs))},
            "prediction": forced_label,
        }

    inputs = tokenizer(low, return_tensors="pt",
                       truncation=True, padding=True)
    with torch.no_grad():
        logits = model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)[0].cpu().numpy()
    pred_id = int(np.argmax(probs))
    return {
        "text": text,
        "probabilities": {id2label[i]: float(p) for i, p in enumerate(probs)},
        "prediction": id2label[pred_id],
    }

__all__ = [
    "classify",
]
