# -*- coding: utf-8 -*-
"""
Stage 2-B: 교육장 Wi-Fi 접속 안내(개인정보) 영역 자동 블러 (독립 모듈)
구조: 흰 안내 카드 검출(ROI) → 카드 crop → PaddleOCR(pocr2 서브프로세스) → net+cred/cred+value 판정
      → True면 카드 전체 영역을 blur 대상. + Wi-Fi 규격 QR.

- easyocr는 소프트포커스 벽 표지를 못 읽어 폐기. PaddleOCR(2.7)를 pro1이 아닌 격리 env `pocr2`에서
  서브프로세스로 호출(모델은 ASCII 경로 C:\\paddle_models — 한글 사용자명 경로 회피).
- Fallback: PaddleOCR 실행 자체 실패 = 보호 우선(카드 블러). OCR 성공 + Wi-Fi False = 미처리(일반 카드).
- 개인정보 비저장: SSID/PW/QR 문자열을 로그·report·파일에 남기지 않는다(헬퍼가 플래그만 반환).
"""
import os, sys, json, subprocess, tempfile, shutil
import numpy as np
import cv2

CONFIG = {
    # 흰 안내 카드 검출
    "card_bright_thr": 165,        # 밝은(흰 종이) 임계
    "card_min_area_ratio": 0.0004, # 이미지 대비 카드 최소 넓이
    "card_max_area_ratio": 0.02,   # 카드 최대 넓이(큰 포스터/화이트보드 제외)
    "card_max_vpos": 0.80,         # 카드 하단이 이미지 상단~중단(벽 사인) 이내
    "card_extent_min": 0.55,       # 외접사각 채움비(사각형다움)
    "card_ar_min": 0.4, "card_ar_max": 2.6,
    "card_pad_ratio": 0.10,        # 카드 영역 패딩
    # QR
    "qr_pad_ratio": 0.12,
    # 블러 강도(통합 엔진이 mask+feather로 적용)
    "blur_kernel_ratio": 0.5,
    "blur_kernel_min": 25,
    # PaddleOCR 실행(pocr2)
    "paddle_python": os.environ.get("DAEASY_PADDLE_PYTHON", r"C:\conda\envs\pocr2\python.exe"),
    "paddle_models": os.environ.get("DAEASY_PADDLE_MODELS", r"C:\paddle_models"),
}
_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "paddle_wifi.py")


def imread_u(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


def imwrite_u(path, img):
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


def blur_bbox(img, x1, y1, x2, y2):
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(img.shape[1], int(x2)), min(img.shape[0], int(y2))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    k = max(CONFIG["blur_kernel_min"], int(max(x2 - x1, y2 - y1) * CONFIG["blur_kernel_ratio"]))
    k |= 1
    img[y1:y2, x1:x2] = cv2.GaussianBlur(img[y1:y2, x1:x2], (k, k), 0)


def detect_cards(img):
    """벽의 작고 고립된 흰 안내 카드 후보 bbox 목록 (Wi-Fi 안내문 ROI 후보)."""
    H, W = img.shape[:2]; area = H * W
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    th = cv2.threshold(g, CONFIG["card_bright_thr"], 255, cv2.THRESH_BINARY)[1]
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cards = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        a = w * h
        if a < CONFIG["card_min_area_ratio"] * area or a > CONFIG["card_max_area_ratio"] * area:
            continue
        if (y + h) > CONFIG["card_max_vpos"] * H:
            continue
        if cv2.contourArea(c) / (a + 1e-9) < CONFIG["card_extent_min"]:
            continue
        ar = w / (h + 1e-6)
        if not (CONFIG["card_ar_min"] <= ar <= CONFIG["card_ar_max"]):
            continue
        cards.append((x, y, w, h))
    return cards


def qr_wifi_bboxes(img):
    """Wi-Fi 규격(WIFI:) QR의 bbox만. 내용은 분류에만 쓰고 폐기."""
    qr = cv2.QRCodeDetector()
    out = []
    try:
        ok, infos, pts, _ = qr.detectAndDecodeMulti(img)
    except Exception:
        ok, pts, infos = False, None, []
    if ok and pts is not None:
        for i, p in enumerate(pts):
            x1, y1, x2, y2 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
            content = infos[i] if i < len(infos) else ""
            out.append((float(x1), float(y1), float(x2), float(y2),
                        bool(isinstance(content, str) and content.upper().startswith("WIFI:"))))
    return out


def _run_paddle(crop_dir):
    """pocr2 서브프로세스로 카드 판정. 반환: (flags dict | None). None=실행 실패(보호 우선)."""
    out_json = os.path.join(crop_dir, "_flags.json")
    if not os.path.exists(CONFIG["paddle_python"]):
        return None
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", DAEASY_PADDLE_MODELS=CONFIG["paddle_models"])
        r = subprocess.run([CONFIG["paddle_python"], _HELPER, crop_dir, out_json],
                           capture_output=True, text=True, env=env, timeout=600)
        if r.returncode != 0 or not os.path.exists(out_json):
            return None
        return json.load(open(out_json, encoding="utf-8"))
    except Exception:
        return None


def run(img_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    # 1) 카드/QR 검출 + 카드 crop 저장
    crop_dir = tempfile.mkdtemp(prefix="daeasy_wifi_")
    per_img = {}
    for fn in files:
        img = imread_u(os.path.join(img_dir, fn))
        if img is None:
            continue
        H, W = img.shape[:2]
        cards = detect_cards(img)
        key = os.path.splitext(fn)[0]
        saved = []
        for i, (x, y, w, h) in enumerate(cards):
            pad = int(CONFIG["card_pad_ratio"] * max(w, h))
            X1, Y1 = max(0, x - pad), max(0, y - pad)
            X2, Y2 = min(W, x + w + pad), min(H, y + h + pad)
            ck = f"{key}__{i}"
            imwrite_u(os.path.join(crop_dir, ck + ".jpg"), img[Y1:Y2, X1:X2])
            saved.append((ck, [X1, Y1, X2, Y2]))
        per_img[fn] = {"cards": saved, "qr": qr_wifi_bboxes(img)}
    # 2) PaddleOCR 판정(pocr2 서브프로세스, 전 카드 일괄)
    flags = _run_paddle(crop_dir) if any(v["cards"] for v in per_img.values()) else {}
    ocr_ran = flags is not None
    flags = flags or {}
    # 3) region 구성
    report = {"method": "white-card ROI + PaddleOCR(pocr2) net+cred/cred+value",
              "privacy": "no SSID/password/QR content stored", "ocr_engine_ran": ocr_ran,
              "config": {k: v for k, v in CONFIG.items() if k != "paddle_python"}, "images": {}}
    tot_blur = tot_keep = 0
    for fn in files:
        if fn not in per_img:
            continue
        img = imread_u(os.path.join(img_dir, fn))
        vis = img.copy(); regions = []
        for ck, bb in per_img[fn]["cards"]:
            x1, y1, x2, y2 = bb
            poly = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            if not ocr_ran:
                act, reason = "blur", "ocr_failed_protect"     # fallback: 보호 우선
            else:
                f = flags.get(ck, {})
                if f.get("wifi"):
                    act, reason = "blur", "wifi_card(paddle)"
                else:
                    act, reason = "keep", "non_wifi_card"
            col = (0, 0, 255) if act == "blur" else (160, 160, 160)
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 4)
            cv2.putText(vis, "wifi " + act, (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2)
            regions.append({"type": "wifi", "bbox": [x1, y1, x2, y2], "poly": poly, "action": act,
                            "method": "blur", "source": "wifi_privacy", "confidence": 0.9 if act == "blur" else 0.0,
                            "reason": reason})
        for (x1, y1, x2, y2, is_wifi) in per_img[fn]["qr"]:
            pad = CONFIG["qr_pad_ratio"] * max(x2 - x1, y2 - y1)
            bb = [int(x1 - pad), int(y1 - pad), int(x2 + pad), int(y2 + pad)]
            poly = [[bb[0], bb[1]], [bb[2], bb[1]], [bb[2], bb[3]], [bb[0], bb[3]]]
            act = "blur" if is_wifi else "keep"
            regions.append({"type": "wifi", "bbox": bb, "poly": poly, "action": act, "method": "blur",
                            "source": "wifi_privacy", "confidence": 0.95 if is_wifi else 0.0,
                            "reason": "wifi_qr" if is_wifi else "non_wifi_qr"})
        imwrite_u(os.path.join(out_dir, "vis_" + fn), vis)
        nb = sum(1 for r in regions if r["action"] == "blur")
        tot_blur += nb; tot_keep += sum(1 for r in regions if r["action"] == "keep")
        report["images"][fn] = {"cards": len(per_img[fn]["cards"]), "wifi_blur": nb, "regions": regions}
        print(f"  {fn[-10:]}: cards={len(per_img[fn]['cards'])} wifi_blur={nb} "
              f"keep={sum(1 for r in regions if r['action']=='keep')}")
    shutil.rmtree(crop_dir, ignore_errors=True)
    with open(os.path.join(out_dir, "wifi블러리포트.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[wifi] 블러 {tot_blur} / keep {tot_keep}  (OCR실행={ocr_ran})")
    print(f"[privacy] SSID/비밀번호/QR 내용 미저장")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
