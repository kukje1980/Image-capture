"""CNN(MobileNetV3-Small) 장면 분류 → ONNX  (2단계: 데이터가 수천 장 모였을 때)

    pip install torch torchvision onnx        # 학습용 PC 에서만 (앱에는 필요 없음)
    python tools/agent_train/train_cnn_onnx.py --data <폴더> \\
        --out assets/models/scene_model.onnx --epochs 10

앱은 onnxruntime 이 설치되어 있고 assets/models/scene_model.onnx 가 있으면 CNN 을 쓰고,
아니면 JSON 모델,
그것도 없으면 규칙 기반으로 돌아간다 (app/agent/scene.py). 입력 128×128 RGB, ImageNet 정규화.
이 스크립트는 torch 가 없는 환경에서는 실행되지 않는다 (train_scene.py 는 torch 없이 동작).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.agent.scene import LABELS  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="append", required=True)
    ap.add_argument("--out", default=str(ROOT / "assets" / "models" / "scene_model.onnx"))
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--batch", type=int, default=32)
    a = ap.parse_args(argv)
    try:
        import torch
        from torch import nn
        from torch.utils.data import ConcatDataset, DataLoader
        from torchvision import datasets, models, transforms
    except ImportError:
        print("torch / torchvision 이 필요합니다: pip install torch torchvision onnx",
              file=sys.stderr)
        return 2

    tf = transforms.Compose([
        transforms.Resize((a.size, a.size)), transforms.ColorJitter(0.2, 0.2, 0.1, 0.02),
        transforms.RandomHorizontalFlip(), transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    sets = []
    for d in a.data:
        ds = datasets.ImageFolder(d, transform=tf)
        # 폴더 이름 → LABELS 순서로 맞춘다 (없는 라벨은 건너뜀)
        ds.samples = [(p, LABELS.index(ds.classes[i])) for p, i in ds.samples
                      if ds.classes[i] in LABELS]
        ds.targets = [t for _, t in ds.samples]
        sets.append(ds)
    data = ConcatDataset(sets)
    loader = DataLoader(data, batch_size=a.batch, shuffle=True, num_workers=2)

    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(LABELS))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    lossf = nn.CrossEntropyLoss()
    for ep in range(a.epochs):
        model.train()
        tot, correct, n = 0.0, 0, 0
        for x, y in loader:
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad()
            out = model(x)
            loss = lossf(out, y)
            loss.backward()
            opt.step()
            tot += float(loss) * len(y)
            correct += int((out.argmax(1) == y).sum())
            n += len(y)
        print(f"epoch {ep + 1}/{a.epochs} loss {tot / n:.3f} acc {correct / n * 100:.1f}%")

    model.eval().cpu()
    dummy = torch.zeros(1, 3, a.size, a.size)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, dummy, str(out), input_names=["input"], output_names=["logits"],
                      dynamic_axes={"input": {0: "batch"}}, opset_version=17)
    out.with_suffix(".json").write_text(json.dumps({"classes": list(LABELS), "size": a.size,
                                                    "mean": [0.485, 0.456, 0.406],
                                                    "std": [0.229, 0.224, 0.225]}, indent=1),
                                        encoding="utf-8")
    print("저장:", out, "(+ .json 클래스 목록). 앱에는 pip install onnxruntime 이 필요합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
