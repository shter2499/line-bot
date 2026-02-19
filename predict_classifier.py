from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
import os
import json
import numpy as np
import threading

MODEL_DIR = "./classifier-edc"
if not os.path.isdir(MODEL_DIR):
    raise SystemExit(
        "Model directory ./classifier-edc not found. Train it first")

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
PRINTER_FORCE_OTHER = {"ปริ้นเตอร์", "ปริ๊นเตอร์", "printer"}

# CUDA Queue support
_cuda_queue_enabled = True
try:
    from cuda_queue import get_cuda_queue_manager
    _queue_manager = get_cuda_queue_manager()
except ImportError:
    _cuda_queue_enabled = False
    _queue_manager = None
    print("[predict_classifier] CUDA queue not available, running directly")


def _classify_internal(text: str):
    """Internal classification function that actually runs the model"""
    # Heuristic override: if mentions 'ปริ้นเตอร์' → force OTHER
    low = text.split('ปัญหาที่พบ:')[1].split("\n")[0] if 'ปัญหาที่พบ:' in text else text.lower()
    
    if any(tok in low for tok in PRINTER_FORCE_OTHER):
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


def classify(text: str):
    """
    Classify text using EDC classifier
    Uses CUDA queue if available to manage GPU usage
    """
    if not _cuda_queue_enabled or _queue_manager is None:
        # No queue available, run directly
        return _classify_internal(text)
    
    # Use CUDA queue - submit task and wait for result
    result_container = {'result': None, 'event': threading.Event()}
    
    def callback(result):
        result_container['result'] = result
        result_container['event'].set()
    
    def error_callback(error):
        print(f"[predict_classifier] Error in queue: {error}")
        result_container['result'] = {
            "text": text,
            "probabilities": {},
            "prediction": "other",
            "error": str(error)
        }
        result_container['event'].set()
    
    _queue_manager.submit_task(
        _classify_internal,
        text,
        callback=callback,
        error_callback=error_callback
    )
    
    # Wait for result (with timeout)
    result_container['event'].wait(timeout=30.0)
    
    if result_container['result'] is None:
        # Timeout - return default
        print(f"[predict_classifier] Timeout waiting for result")
        return {
            "text": text,
            "probabilities": {},
            "prediction": "other",
            "error": "timeout"
        }
    
    return result_container['result']


__all__ = [
    "classify",
]
