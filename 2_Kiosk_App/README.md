# GACHA-BIN 🤖♻️

เครื่องแยกขวดพลาสติก / โลหะ อัตโนมัติ + ระบบรางวัล gacha
**ฝั่งโปรแกรม**: classification ด้วย YOLO11n-cls (Ultralytics)

| ตัวเลขหลัก | ค่า |
|---|---|
| โมเดล | YOLO11n-cls (1.53M params, 3.2 GFLOPs) |
| Classes | `metal` / `plastic` |
| ข้อมูล | 892 รูป (train 714 / val 178) |
| **Top-1 Accuracy** | **0.978** (สูงสุด 0.983) |
| Top-5 Accuracy | 1.000 |
| Inference | ~4.2 ms/ภาพ (RTX 4050) |
| Target machine | Raspberry Pi OS (Debian) + Docker + กล้อง USB |

---

## 📁 โครงสร้าง repo

```
├── scripts/
│   ├── prepare_data.py      # split ข้อมูล → train/val (Bottle_dataset)
│   └── webcam_classify.py   # กล้อง realtime classify (works PC + Pi)
├── model/
│   └── best.pt              # โมเดลเทรนเสร็จ (ใช้ใน production ได้เลย)
├── data/
│   └── data.yaml            # dataset config (0: metal, 1: plastic)
├── results/                 # log การเทรน (metrics + กราฟ + args)
├── sample/                  # รูปตัวอย่าง metal/plastic (ชุดเล็กสำหรับ demo)
├── deploy/                  # 🆕 สำหรับ Raspberry Pi
│   ├── Dockerfile           #   image arm64 (python + torch CPU + ultralytics + opencv)
│   ├── docker-compose.yml   #   map กล้อง USB + config
│   ├── requirements-pi.txt  #   dependencies สำหรับ Pi
│   ├── pi_cam.py            #   headless inference → JSON (ไม่มี GUI)
│   └── README.md            #   คู่มือติดตั้งบน Pi
├── requirements.txt
└── CHANGELOG.md
```

---

## 🚀 วิธีใช้

### 1) เทสกับรูปเดียว
```powershell
yolo classify predict model=model\best.pt source=path\to\image.jpg
```

### 2) กล้อง realtime (webcam / USB)
```powershell
$env:YOLO_OFFLINE = "true"          # ข้ามเช็คเน็ต ตอนเน็ตพังบ่อย
python scripts\webcam_classify.py --model model\best.pt
# ถ้าไม่มี GPU (เช่น Raspberry Pi): เพิ่ม --device cpu
```

### 3) (Dev) เทรนต่อจากที่ค้าง
```powershell
yolo classify train model=yolo11n-cls.pt data=data\data.yaml epochs=50 imgsz=224 device=0
```

---

## 🔬 Pipeline ที่ใช้

1. **ข้อมูล**: 1,007 รูปขวด (metal: `0116–0525`, plastic: `0526–1007`) — กัน `0001–0115` ไว้เป็นชุดเทสลับ
2. **Split** (`scripts/prepare_data.py`): 80/20 → train 714 / val 178
3. **เทรน**: YOLO11n-cls, 50 epochs, imgsz 224, RTX 4050
4. **ประเมิน**: top1 0.978, top5 1.000, loss ≈ 0.03–0.06
5. **Realtime**: `webcam_classify.py` — ผ่านการเทสด้วย webcam จริง (plastic + metal ถูกต้อง)

---

## 📦 การลงบน Raspberry Pi

ชุด Docker + สคริปต์ headless อยู่ใน [`deploy/`](deploy/README.md):

```bash
# บน Pi ตัวจริง (arm64):
git clone https://github.com/Phuwaset/gachabin.git && cd gachabin
docker compose -f deploy/docker-compose.yml up -d --build
```

- รองรับกล้อง USB ผ่าน `/dev/video0` → ผลเป็น **JSON 1 บรรทัด/วิชา** (class + conf) พร้อมให้ controller ใช้
- Image เป็น arm64: python 3.13 + torch (CPU) + ultralytics + opencv-headless
- หน้า git ถ้า export โมเดลเป็น ONNX แต่เน้นประหยัด/เร็ว มาช่วยด้วย (ดู roadmap)

> หมายเหตุเน็ต: จุดนี้โหลดจาก GitHub/PyPI ไม่เสถียร → ใช้ `curl.exe -L --retry 8` และ `YOLO_OFFLINE=true` เมื่อรัน ultralytics