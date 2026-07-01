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
from sklearn.metrics import f1_score, precision_score, recall_score, classification_report
import os

# 1) Load CSV (auto-detect filename)
# csv_path = "cr_data.csv"
csv_path = "data.csv"
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

# Support a variety of column names: text/input/Message for text, key/Key/label for label
text_column_name = _find_col(["text", "input", "message"])  # case-insensitive
label_column_name = _find_col(["key", "label"])             # case-insensitive
if text_column_name is None or label_column_name is None:
    raise ValueError(
        f"CSV must contain a text column (one of: text/input/Message) and a label column (key/label). Columns found: {raw_dataset.column_names}"
    )

def _is_valid_row(ex: Dict) -> bool:
    text_value = ex.get(text_column_name)
    label_value = ex.get(label_column_name)
    return isinstance(text_value, str) and text_value.strip() and isinstance(label_value, str) and label_value.strip()

filtered_dataset = raw_dataset.filter(_is_valid_row)

# 2) Normalize labels to binary
raw_label_values = [_norm(v) for v in filtered_dataset[label_column_name]]
normalized_labels = ["edc" if (v and "edc" in v) else "other" for v in raw_label_values]
# normalized_labels = ["cr" if (v and "cr" in v) else "other" for v in raw_label_values]

# label2id = {"other": 0, "cr": 1}
label2id = {"other": 0, "edc": 1}
id2label = {label_id: label_name for label_name, label_id in label2id.items()}
label_id_list = [label2id[x] for x in normalized_labels]

# Build final dataset
text_samples = filtered_dataset[text_column_name]
full_dataset = Dataset.from_dict({"text": text_samples, "label": label_id_list})

# 3) Split
train_test_splits = full_dataset.train_test_split(test_size=0.2, seed=42)
train_dataset = train_test_splits["train"]
eval_dataset = train_test_splits["test"]

# 4) Tokenize
pretrained_model_name = "distilbert-base-multilingual-cased"
tokenizer = AutoTokenizer.from_pretrained(pretrained_model_name)

def tokenize_fn(batch: Dict[str, List[str]]):
    return tokenizer(batch["text"], padding="max_length", truncation=True, max_length=192)

train_tokenized = train_dataset.map(tokenize_fn, batched=True)
eval_tokenized = eval_dataset.map(tokenize_fn, batched=True)

# 5) Metrics
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = float((preds == labels).mean())
    f1 = float(f1_score(labels, preds, average="macro"))
    precision = float(precision_score(labels, preds, average="macro", zero_division=0))
    recall = float(recall_score(labels, preds, average="macro", zero_division=0))
    return {
        "accuracy": acc,
        "f1_macro": f1,
        "precision": precision,
        "recall": recall,
    }

# 6) TrainingArgs
training_args = TrainingArguments(
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
classifier_model = AutoModelForSequenceClassification.from_pretrained(
    pretrained_model_name,
    num_labels=2,
    id2label=id2label,
    label2id=label2id,
)

trainer = Trainer(
    model=classifier_model,
    args=training_args,
    train_dataset=train_tokenized,
    eval_dataset=eval_tokenized,
    compute_metrics=compute_metrics,
)

trainer.train()

# --- Post-training evaluation on eval set ---
eval_results = trainer.evaluate()
print("\n=== Eval Metrics ===")
for metric_name, metric_value in eval_results.items():
    print(f"  {metric_name}: {metric_value:.4f}" if isinstance(metric_value, float) else f"  {metric_name}: {metric_value}")

# Classification report + confusion matrix
eval_predictions = trainer.predict(eval_tokenized)
predicted_labels = np.argmax(eval_predictions.predictions, axis=-1)
true_labels = eval_predictions.label_ids
label_name_list = [id2label[i] for i in range(len(id2label))]
print("\n=== Classification Report ===")
print(classification_report(true_labels, predicted_labels, target_names=label_name_list))

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix
    confusion_mat = confusion_matrix(true_labels, predicted_labels)
    disp = ConfusionMatrixDisplay(confusion_matrix=confusion_mat, display_labels=label_name_list)
    disp.plot(colorbar=False)
    plt.title("Confusion Matrix")
    plt.tight_layout()
    plt.savefig("confusion_matrix.png")
    print("Confusion matrix saved to confusion_matrix.png")
except Exception as e:
    print("Confusion matrix plot skipped:", e)

# output_model_dir = "./classifier-cr"
output_model_dir = "./classifier-edc"
os.makedirs(output_model_dir, exist_ok=True)
trainer.save_model(output_model_dir)
tokenizer.save_pretrained(output_model_dir)

# Save label mapping for inference
with open(os.path.join(output_model_dir, "label_mapping.json"), "w", encoding="utf-8") as f:
    json.dump({"label2id": label2id, "id2label": id2label}, f, ensure_ascii=False, indent=2)

print("Saved binary classifier to", output_model_dir)

# 8) Quick demo inference
try:
    import torch
    demo_sample_text = "พร้อมเพย์ไม่เข้า เครื่องค้าง edc"
    demo_inputs = tokenizer(demo_sample_text, return_tensors="pt", truncation=True, padding=True)
    classifier_model.eval()
    with torch.no_grad():
        demo_probs = torch.softmax(classifier_model(**demo_inputs).logits, dim=-1)[0].tolist()
    demo_pred_id = int(np.argmax(demo_probs))
    print("Sample:", demo_sample_text)
    print("Pred:", id2label[demo_pred_id], "probs=", demo_probs)
except Exception as e:
    print("Demo inference skipped:", e)
