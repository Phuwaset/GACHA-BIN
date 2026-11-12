# -*- coding: utf-8 -*-
"""
auto_capture_pi.py — Script สำหรับบันทึก Dataset จากกล้องจริงบน Raspberry Pi
สำหรับโปรเจกต์ GACHA-BIN (Smart Vision Recycling Kiosk)

วิธีใช้งาน:
    python auto_capture_pi.py --cls plastic --target 1200
    python auto_capture_pi.py --cls metal --target 1200

การควบคุม:
    - [SPACEBAR] : สลับระหว่าง 'กำลังบันทึก (REC)' กับ 'หยุดชั่วคราว (PAUSE)'
    - [Q] หรือ [ESC] : บันทึกเสร็จสิ้นและปิดโปรแกรม
"""
import argparse
import os
import sys
import time
from pathlib import Path
import cv2

# กำหนดสัดส่วน Center ROI ให้ตรงกับ detector.py ของระบบ Kiosk
ROI_WIDTH_RATIO = 0.65
ROI_HEIGHT_RATIO = 0.75


def parse_args():
    ap = argparse.ArgumentParser(description="GACHA-BIN Camera Dataset Collector")
    ap.add_argument("--cls", required=True, choices=["plastic", "metal"],
                    help="คลาสที่ต้องการบันทึก: plastic หรือ metal")
    ap.add_argument("--source", type=int, default=0, help="Camera index (ค่าเริ่มต้น 0)")
    ap.add_argument("--width", type=int, default=640, help="Camera frame width")
    ap.add_argument("--height", type=int, default=480, help="Camera frame height")
    ap.add_argument("--target", type=int, default=1200, help="เป้าหมายจำนวนภาพที่ต้องการ (default: 1200)")
    ap.add_argument("--step", type=int, default=4, help="บันทึกทุกๆ กี่เฟรม (default: 4 เพื่อลดภาพซ้ำ)")
    ap.add_argument("--output", default="dataset_pi", help="โฟลเดอร์ปลายทาง")
    return ap.parse_args()


def main():
    args = parse_args()

    save_dir = Path(__file__).parent / args.output / args.cls
    save_dir.mkdir(parents=True, exist_ok=True)

    # นับจำนวนภาพเดิมที่มีอยู่แล้ว
    existing_files = list(save_dir.glob("*.jpg"))
    saved_count = len(existing_files)

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        print(f"[ERROR] ไม่สามารถเปิดกล้องได้ (source={args.source}) ตรวจสอบการเชื่อมต่อสาย USB")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    is_recording = False
    frame_counter = 0

    print("=" * 65)
    print(f"  GACHA-BIN Dataset Collector — บันทึกคลาส: [{args.cls.upper()}]")
    print(f"  โฟลเดอร์บันทึก: {save_dir}")
    print(f"  มีภาพเดิมอยู่แล้ว: {saved_count} ภาพ | เป้าหมาย: {args.target} ภาพ")
    print("=" * 65)
    print("  [SPACE] = เริ่มบันทึก / หยุดชั่วคราว (REC / PAUSE)")
    print("  [Q/ESC] = เสร็จสิ้น / ปิดโปรแกรม")
    print("=" * 65)

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        h, w = frame.shape[:2]
        rw = int(w * ROI_WIDTH_RATIO)
        rh = int(h * ROI_HEIGHT_RATIO)
        rx1 = max(0, (w - rw) // 2)
        ry1 = max(0, (h - rh) // 2)
        rx2 = min(w, rx1 + rw)
        ry2 = min(h, ry1 + rh)
        roi = frame[ry1:ry2, rx1:rx2]

        display_frame = frame.copy()

        # วาดกรอบ Center ROI
        box_color = (0, 255, 0) if is_recording else (0, 165, 255)
        cv2.rectangle(display_frame, (rx1, ry1), (rx2, ry2), box_color, 2)

        # บันทึกภาพ
        if is_recording:
            frame_counter += 1
            if frame_counter % args.step == 0:
                saved_count += 1
                filename = f"{args.cls}_{int(time.time())}_{saved_count:05d}.jpg"
                # บันทึกเฉพาะภาพบริเวณ ROI ที่ตรงกับที่โมเดลมองเห็น
                roi_resized = cv2.resize(roi, (224, 224), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(save_dir / filename), roi_resized)

                if saved_count >= args.target:
                    is_recording = False
                    print(f"\n[SUCCESS] ครบเป้าหมาย {args.target} ภาพเรียบร้อยแล้ว!")

        # แสดง HUD บนหน้าจอ
        status_text = f"STATUS: {'RECORDING (REC)' if is_recording else 'PAUSED'}"
        cv2.putText(display_frame, status_text, (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, box_color, 2)

        progress_text = f"CLASS: {args.cls.upper()} | SAVED: {saved_count}/{args.target}"
        cv2.putText(display_frame, progress_text, (20, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        instruction = "Press [SPACE] to toggle REC | [Q] to quit"
        cv2.putText(display_frame, instruction, (20, h - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

        cv2.imshow("GACHA-BIN Data Collector", display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(' '):
            is_recording = not is_recording
            print(f"[{'REC' if is_recording else 'PAUSE'}] บันทึกไปแล้ว {saved_count}/{args.target} ภาพ")
        elif key in (ord('q'), 27):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[DONE] เสร็จสิ้น! ภาพทั้งหมด {saved_count} ภาพถูกบันทึกไว้ที่: {save_dir}")


if __name__ == "__main__":
    main()
