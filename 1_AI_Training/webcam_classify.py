# -*- coding: utf-8 -*-
"""
webcam_classify.py — Real-time bottle classification (plastic/metal) สำหรับ GACHA-BIN
- ใช้โมเดล YOLO11n-cls ที่เทรนแล้ว (best.pt)
- รันได้ทั้งบน Windows (dev) และ Raspberry Pi OS (Debian) ด้วยกล้อง USB

วิธีรัน:
    python webcam_classify.py --model best.pt                 # กล้องตัวแรก, GPU
    python webcam_classify.py --model best.pt --device cpu    # ถ้าไม่มี GPU (เช่น Pi)
กด Q หรือ ESC เพื่อปิด
"""
import argparse
import os
import sys
import time

import cv2
from ultralytics import YOLO


def parse_args():
    default_model = "models/best.pt" if os.path.exists("models/best.pt") else "best.pt"
    ap = argparse.ArgumentParser(description="GACHA-BIN realtime bottle classifier")
    ap.add_argument("--model", default=default_model, help="path to trained .pt model")
    ap.add_argument("--source", type=int, default=0,
                    help="camera index (0 = first, 1 = second)")
    ap.add_argument("--device", default="0",
                    help="'0' = GPU, 'cpu' = CPU (ใช้บน Raspberry Pi)")
    ap.add_argument("--imgsz", type=int, default=224,
                    help="input size (default 224 as training)")
    ap.add_argument("--conf", type=float, default=0.25,
                    help="confidence threshold")
    ap.add_argument("--width", type=int, default=640, help="camera width")
    ap.add_argument("--height", type=int, default=480, help="camera height")
    return ap.parse_args()


def main():
    args = parse_args()

    # 1) โหลดโมเดล
    print(f"Loading model: {args.model}")
    model = YOLO(args.model)
    names = getattr(model, "names", None) or {0: "plastic", 1: "metal"}

    # 2) เปิดกล้อง
    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        print(f"[ERROR] เปิดกล้องไม่ได้ (source={args.source}) — ตรวจว่าเสียบ USB แล้ว / ลอง --source 1")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    print("Camera OK! กด Q หรือ ESC เพื่อปิด\n")

    fps = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            print("[WARN] อ่านเฟรมไม่ได้ (ถอดสายกล้อง?) หยุด...")
            break

        t0 = time.time()

        # 3) ทำนายทั้งเฟรม (classification)
        results = model(frame, imgsz=args.imgsz, device=args.device,
                        conf=args.conf, verbose=False)
        r = results[0]

        if r.probs is not None:
            idx = int(r.probs.top1)
            conf = float(r.probs.top1conf)
            label = names.get(idx, str(idx))

            # สี: พลาสติก = เขียว, โลหะ = แดง (BGR)
            color = (0, 200, 0) if "plastic" in label.lower() else (0, 0, 220)

            # แสดงผลหลัก: ชื่อคลาส + ความมั่นใจ
            cv2.putText(frame, f"{label}  {conf:.2f}",
                        (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)

            # แสดงคะแนนทั้ง 2 คลาส
            for i in range(len(r.probs.data)):
                prob = float(r.probs.data[i].item())
                cv2.putText(frame, f"{names.get(i)}: {prob:.2f}",
                            (20, 80 + i * 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.7, (255, 255, 255), 2)

        # FPS (ค่าเฉลี่ยแบบเลื่อน)
        dt = max(time.time() - t0, 1e-4)
        fps = fps * 0.9 + (1.0 / dt) * 0.1
        cv2.putText(frame, f"FPS: {fps:.1f}", (20, frame.shape[0] - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

        cv2.imshow("GACHA-BIN", frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):  # q / Q / ESC
            break

    cap.release()
    cv2.destroyAllWindows()
    print("ปิดกล้องแล้ว — Bye!")


if __name__ == "__main__":
    main()