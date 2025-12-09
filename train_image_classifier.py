from __future__ import annotations

import os
from pathlib import Path
from typing import List

import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms, models


# -----------------------------
# Config
# -----------------------------
DATA_DIR = Path("image_data")  # expect: image_data/train/edc, image_data/train/not_edc, image_data/val/...
print(f"[INFO] Using data directory: {DATA_DIR}")
OUTPUT_DIR = Path("classifier-image-edc")
BATCH_SIZE = 32
NUM_EPOCHS = 5
LR = 1e-4
NUM_WORKERS = 2
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _build_transforms() -> tuple[transforms.Compose, transforms.Compose]:
    # Standard ImageNet normalization
    train_tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])

    val_tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(
            mean=[0.485, 0.456, 0.406],
            std=[0.229, 0.224, 0.225],
        ),
    ])
    return train_tf, val_tf


def _load_datasets(train_tf, val_tf):
    train_root = DATA_DIR / "train"
    val_root = DATA_DIR / "val"

    if not train_root.exists():
        raise FileNotFoundError(
            f"ไม่พบโฟลเดอร์ {train_root}. โปรดสร้างโครงแบบ image_data/train/<class_name>/image.jpg"
        )

    if not val_root.exists():
        raise FileNotFoundError(
            f"ไม่พบโฟลเดอร์ {val_root}. โปรดสร้างโครงแบบ image_data/val/<class_name>/image.jpg"
        )

    train_ds = datasets.ImageFolder(train_root, transform=train_tf)
    val_ds = datasets.ImageFolder(val_root, transform=val_tf)

    if len(train_ds.classes) < 2:
        raise ValueError(
            f"ต้องมีอย่างน้อย 2 คลาสใน train (เช่น edc, not_edc) แต่เจอ {train_ds.classes}"
        )

    print("[INFO] Classes:", train_ds.classes)
    return train_ds, val_ds


def _build_model(num_classes: int) -> nn.Module:
    # ใช้ ResNet18 pretrained บน ImageNet แล้ว fine-tune layer สุดท้าย
    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    in_features = model.fc.in_features
    model.fc = nn.Linear(in_features, num_classes)
    return model


def _train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    epoch: int,
) -> None:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0

    for imgs, labels in loader:
        imgs = imgs.to(DEVICE)
        labels = labels.to(DEVICE)

        optimizer.zero_grad()
        outputs = model(imgs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * imgs.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    avg_loss = total_loss / max(total, 1)
    acc = correct / max(total, 1)
    print(f"[TRAIN] epoch={epoch} loss={avg_loss:.4f} acc={acc:.4f}")


def _eval_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    epoch: int,
) -> None:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for imgs, labels in loader:
            imgs = imgs.to(DEVICE)
            labels = labels.to(DEVICE)

            outputs = model(imgs)
            loss = criterion(outputs, labels)

            total_loss += loss.item() * imgs.size(0)
            preds = outputs.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    avg_loss = total_loss / max(total, 1)
    acc = correct / max(total, 1)
    print(f"[VAL]   epoch={epoch} loss={avg_loss:.4f} acc={acc:.4f}")


def main() -> None:
    print(f"[INFO] Using device: {DEVICE}")
    train_tf, val_tf = _build_transforms()
    train_ds, val_ds = _load_datasets(train_tf, val_tf)

    train_loader = DataLoader(
        train_ds,
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=NUM_WORKERS,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=NUM_WORKERS,
    )

    num_classes = len(train_ds.classes)
    model = _build_model(num_classes).to(DEVICE)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR)

    for epoch in range(1, NUM_EPOCHS + 1):
        _train_one_epoch(model, train_loader, criterion, optimizer, epoch)
        _eval_one_epoch(model, val_loader, criterion, epoch)

    # Save model + class mapping
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    model_path = OUTPUT_DIR / "model.pt"
    torch.save(model.state_dict(), model_path)

    classes_path = OUTPUT_DIR / "classes.txt"
    with open(classes_path, "w", encoding="utf-8") as f:
        for cls in train_ds.classes:
            f.write(cls + "\n")

    print(f"[INFO] Saved model to {model_path}")
    print(f"[INFO] Saved class names to {classes_path}")


if __name__ == "__main__":
    main()
