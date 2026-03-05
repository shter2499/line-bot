from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import torch
from torchvision import models, transforms
from PIL import Image

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_DIR = Path("classifier-image-edc")
MODEL_PATH = MODEL_DIR / "model.pt"
CLASSES_PATH = MODEL_DIR / "classes.txt"


if not MODEL_PATH.is_file() or not CLASSES_PATH.is_file():
    raise SystemExit(
        "Image model not found. โปรดรัน train_image_classifier.py ให้ได้ classifier-image-edc/model.pt และ classes.txt ก่อน"
    )

# โหลด class names
with open(CLASSES_PATH, encoding="utf-8") as f:
    CLASSES = [line.strip() for line in f if line.strip()]


def _load_model() -> torch.nn.Module:
    model = models.resnet18(weights=None)
    in_features = model.fc.in_features
    model.fc = torch.nn.Linear(in_features, len(CLASSES))

    state_dict = torch.load(MODEL_PATH, map_location=DEVICE)
    model.load_state_dict(state_dict)
    model.to(DEVICE)
    model.eval()
    return model


_MODEL = _load_model()


_TRANSFORM = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(
        mean=[0.485, 0.456, 0.406],
        std=[0.229, 0.224, 0.225],
    ),
])

# CUDA Queue removed - running directly
print("[predict_image_edc] Running directly without CUDA queue")


def _classify_image_internal(image_path: str) -> Dict[str, object]:
    """จำแนกรูปว่าเป็นคลาสใด (เช่น edc / not_edc).

    Returns dict:
        {
          "path": <image_path>,
          "prediction": <class_name>,
          "probabilities": {class_name: prob, ...}
        }
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    img = Image.open(image_path).convert("RGB")
    x = _TRANSFORM(img).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        logits = _MODEL(x)[0]
        probs = torch.softmax(logits, dim=-1).cpu().tolist()

    pred_idx = int(torch.argmax(logits).item())
    pred_label = CLASSES[pred_idx]

    return {
        "path": image_path,
        "probabilities": {cls: float(p) for cls, p in zip(CLASSES, probs)},
        "prediction": pred_label,
    }


def classify_image(image_path: str) -> Dict[str, object]:
    """
    Classify image using EDC image classifier
    Runs directly without CUDA queue
    """
    return _classify_image_internal(image_path)


__all__ = ["classify_image"]
