import shutil, random
from pathlib import Path

SRC = Path(__file__).parent / "dataset"
DST = Path(__file__).parent / "Bottle_dataset"
random.seed(42)                     # ให้ split คงเดิมทุกครั้งที่รัน

metal   = [f"{i:04d}.jpg" for i in range(116, 526)]    # 0116-0525
plastic = [f"{i:04d}.jpg" for i in range(526, 1008)]   # 0526-1007

for cls, names in [("metal", metal), ("plastic", plastic)]:
    random.shuffle(names)
    n_val = round(len(names) * 0.2)                     # กัน 20% เป็น val
    for split, files in [("val", names[:n_val]), ("train", names[n_val:])]:
        out = DST / split / cls
        out.mkdir(parents=True, exist_ok=True)
        for n in files:
            shutil.copy(SRC / n, out / n)
    print(f"{cls}: train={len(names)-n_val}  val={n_val}")