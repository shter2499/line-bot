from __future__ import annotations
from typing import Dict, List
import json
import numpy as np
from datasets import load_dataset, Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    TrainingArguments,
    Trainer,
)
import os

# 1) Load CSV (auto-detect filename)
# csv_path = "cr_data.csv"
csv_path = "data.csv"
raw = load_dataset("csv", data_files=csv_path, split="train")

def _norm(s: str | None) -> str | None:
    if s is None:
        return None
    return " ".join(str(s).strip().lower().split()) or None

def _find_col(possible: List[str]) -> str | None:
    lower_map = {c.lower(): c for c in raw.column_names}
    for p in possible:
        if p in lower_map:
            return lower_map[p]
    return None

# Support a variety of column names: text/input/Message for text, key/Key/label for label
text_col = _find_col(["text", "input", "message"])  # case-insensitive
key_col = _find_col(["key", "label"])  # case-insensitive
if text_col is None or key_col is None:
    raise ValueError(
        f"CSV must contain a text column (one of: text/input/Message) and a label column (key/label). Columns found: {raw.column_names}"
    )

def _is_valid_row(ex: Dict) -> bool:
    t = ex.get(text_col)
    k = ex.get(key_col)
    return isinstance(t, str) and t.strip() and isinstance(k, str) and k.strip()

dataset = raw.filter(_is_valid_row)

# 2) Normalize labels to binary
labels_raw = [_norm(v) for v in dataset[key_col]]
binary_labels = ["edc" if (v and "edc" in v) else "other" for v in labels_raw]
# binary_labels = ["cr" if (v and "cr" in v) else "other" for v in labels_raw]

# label2id = {"other": 0, "cr": 1}
label2id = {"other": 0, "edc": 1}
id2label = {v: k for k, v in label2id.items()}
ids = [label2id[x] for x in binary_labels]

# Build final dataset
texts = dataset[text_col]
data_ds = Dataset.from_dict({"text": texts, "label": ids})

# 3) Split
splits = data_ds.train_test_split(test_size=0.2, seed=42)
train_ds = splits["train"]
eval_ds = splits["test"]

# 4) Tokenize
model_name = "distilbert-base-multilingual-cased"
tokenizer = AutoTokenizer.from_pretrained(model_name)

def tokenize_fn(batch: Dict[str, List[str]]):
    return tokenizer(batch["text"], padding=True, truncation=True, max_length=192)

train_tok = train_ds.map(tokenize_fn, batched=True)
eval_tok = eval_ds.map(tokenize_fn, batched=True)

# 5) Metrics
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = (preds == labels).mean()
    return {"accuracy": float(acc)}

# 6) TrainingArgs
args = TrainingArguments(
    output_dir="./results-edc-binary",
    per_device_train_batch_size=16,
    per_device_eval_batch_size=32,
    num_train_epochs=3,
    learning_rate=2e-5,
    eval_strategy="epoch",
    save_strategy="no",
    logging_steps=25,
    report_to="tensorboard", 
)

# 7) Model
model = AutoModelForSequenceClassification.from_pretrained(
    model_name,
    num_labels=2,
    id2label=id2label,
    label2id=label2id,
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=train_tok,
    eval_dataset=eval_tok,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
)

trainer.train()

# save_dir = "./classifier-cr"
save_dir = "./classifier-edc"
os.makedirs(save_dir, exist_ok=True)
trainer.save_model(save_dir)
tokenizer.save_pretrained(save_dir)

# Save label mapping for inference
with open(os.path.join(save_dir, "label_mapping.json"), "w", encoding="utf-8") as f:
    json.dump({"label2id": label2id, "id2label": id2label}, f, ensure_ascii=False, indent=2)

print("Saved binary classifier to", save_dir)

# 8) Quick demo inference
try:
    import torch
    sample = "พร้อมเพย์ไม่เข้า เครื่องค้าง edc"
    inputs = tokenizer(sample, return_tensors="pt", truncation=True, padding=True)
    model.eval()
    with torch.no_grad():
        probs = torch.softmax(model(**inputs).logits, dim=-1)[0].tolist()
    pred = int(np.argmax(probs))
    print("Sample:", sample)
    print("Pred:", id2label[pred], "probs=", probs)
except Exception as e:
    print("Demo inference skipped:", e)
