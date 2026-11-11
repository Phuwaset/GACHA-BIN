# GACHA-BIN — Smart Vision Recycling Kiosk
> โครงการระบบตู้รีไซเคิลอัจฉริยะ คัดแยกกระป๋อง/ขวดพลาสติก และสะสมแต้มแลกรางวัล (ระดับ ปวช./ปวส.)
> เอกสารประกอบโครงงาน ว-สอศ-3 หมวดที่ 5

---

## ผังโครงสร้างโปรเจกต์ (Clean Project Architecture)

```text
FL202603_06_Programimg-Design/
│
├── 1_AI_Training/              # ส่วนที่ 1: การเทรนสมองกล AI (YOLO11 Classification)
│   ├── dataset/                # ชุดภาพถ่ายจริงในช่องสแกน (Bottle_Images)
│   ├── Bottle_dataset/         # ข้อมูลที่แบ่ง Train (80%) และ Val (20%)
│   ├── prepare_data.py         # สคริปต์เตรียมและแบ่งข้อมูลภาพ
│   ├── webcam_classify.py      # สคริปต์ทดสอบกล้องสดเดี่ยวๆ แสดงผล FPS และความแม่นยำ
│   ├── models/                 # โมเดล best.pt และ weights ที่เทรนเสร็จแล้ว
│   └── runs/                   # กราฟและสถิติผลการเทรน (Accuracy 98.3%)
│
├── 2_Kiosk_App/                # ส่วนที่ 2: ระบบหน้าตู้จริง (Unified Single-Port Host)
│   ├── backend/                # หัวใจหลักของตู้ (FastAPI + Vision + HAL + SQLite WAL)
│   │   ├── app/
│   │   │   ├── api/            # REST API (Auth Numpad, Gacha Spin)
│   │   │   ├── hal/            # Hardware Abstraction Layer (RPi.GPIO & Mock)
│   │   │   ├── services/       # SQLite WAL Database Models (Master-Detail)
│   │   │   ├── vision/         # 4-Stage Invariants Engine & CameraManager
│   │   │   ├── websocket/      # WebSocket สตรีมภาพสดและคำนวณแต้มแบบ Real-time
│   │   │   ├── static/         # หน้าจอ Kiosk Web UI (HTML5 + CSS3 + ES6)
│   │   │   │   └── index.html  # Single-Page Kiosk UI (Eco-Impact, ธีม 🌙/☀️, 2 ภาษา 🌐)
│   │   │   ├── config.py       # คอนฟิกระบบและเกณฑ์แต้ม
│   │   │   └── main.py         # จุดสตาร์ต FastAPI และ Rotating File Logger
│   │   └── requirements.txt    # ไลบรารี Python สำหรับ Backend
│   │
│   ├── models/                 # โมเดล AI ประจำตู้ (best.pt)
│   ├── run_kiosk.sh            # สคริปต์คลิกเดียวรันทั้งตู้ด้วย Chromium Kiosk Mode
│   └── requirements.txt        # ไลบรารี Python หลัก (Torch, Ultralytics, OpenCV)
│
└── 3_Docs/                     # ส่วนที่ 3: เอกสารรูปเล่ม แผนงาน และผังวงจร (ว-สอศ-3)
    └── Concept_Design/         # ไดอะแกรมระบบและเอกสารพิมพ์เขียว
        └── gachabin_flowchart_sequence.html  # แผนผังระบบ 4 ส่วน พร้อมปุ่มพิมพ์ PDF A4
```

---

## ขั้นตอนการทดสอบและการใช้งาน

### 1. ทดสอบกล้องและ AI เดี่ยวๆ (บนคอมพิวเตอร์ หรือ Pi)
```bash
cd 1_AI_Training
python webcam_classify.py
```

### 2. รันระบบตู้ Kiosk บนคอมพิวเตอร์ (Windows Dev Mode)
```powershell
cd 2_Kiosk_App/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
*เปิดเบราว์เซอร์ไปที่ `http://localhost:8000` เพื่อใช้งานหน้าตู้ Kiosk*

### 3. รันระบบตู้ Kiosk เต็มรูปแบบบน Raspberry Pi
```bash
cd 2_Kiosk_App
bash run_kiosk.sh
```
*ระบบจะเคลียร์พอร์ต 8000, สตาร์ต FastAPI Backend และเปิด Chromium Kiosk Mode เต็มหน้าจออัตโนมัติ*
