# -*- coding: utf-8 -*-
"""
Stage 2-A: 개인 노트북 '화면 패널만' 자동 Gaussian Blur (독립 모듈)
파이프라인: YOLOX(laptop 검출) -> 화면 패널 추출(cv2/numpy) -> 오탐 필터 -> Gaussian Blur -> 검증

- 기존 onnxruntime / numpy / cv2 재사용. 새 패키지/환경 없음.
- 모델: ~/.daeasy/models/yolox_s.onnx (Megvii YOLOX, Apache-2.0)
- Stage 1(face_blur.py)과 통합하지 않음. 독립 입출력.
- OCR 미사용. 화면 내부 문자열을 읽거나 저장하지 않음.
"""
import os, sys, json
import numpy as np
import cv2
import onnxruntime as ort

CONFIG = {
    "yolox_input": 640,            # YOLOX 고정 입력
    "det_conf": 0.10,              # laptop objectness*cls 임계 (낮춰 약하게 잡히는 실제 화면까지 포착)
    "low_conf_thr": 0.18,          # 이 미만의 약검출은 아래 색 게이트를 추가로 요구(단색 오탐 배제)
    "low_conf_colf_min": 5.0,      # 저conf 검출은 colf>=이값(색 있는 내용)만 화면 — 단색 금속뚜껑/키보드 배제
    "nms_thr": 0.45,
    "laptop_cls": 63,              # COCO: laptop
    "tv_cls": 62,                  # COCO: tv/monitor (기록용, 블러 안 함)
    "min_laptop_px": 40,           # 너무 작은 노트북은 정보량 적음 -> skip
    # 화면 패널 추출 (내용-기반: 내용 있는 디스플레이만 = 엣지/수평구조 높음)
    "panel_min_area_ratio": 0.06,  # laptop ROI 대비 내용영역 최소 넓이
    "panel_ar_max": 4.5,           # 회전사각형 장/단축비 상한(가는 모서리/케이블 제외)
    "content_dens_thr": 0.06,      # 국소 엣지밀도 임계(이상=내용 영역)
    # 화면 판정(내용 화면 vs 균일 뚜껑/본체/어깨) — 둘 중 하나면 화면
    "screen_hstruct_min": 0.68,    # 수평구조(텍스트줄/UI바) 비율 하한 — 내용화면 vs 뒷면 분리 핵심
    "screen_ed_min": 0.15,         # 내부 엣지밀도(CLAHE) 하한(보조: 내용 매우 많은 화면)
    "screen_colf_min": 8.0,        # 색 다채로움 하한 — 색 있는 희소화면(브라우저/문서) 포착, 단색 뒷면 제외
    "screen_panel_ar_max": 2.3,    # 패널 종횡비 상한 — 실제 화면 ~1.2~2.0, 이상이면 케이블/키보드/책상 strip
    "screen_skin_max": 0.35,       # 피부색 비율 상한(어깨/손 제외)
    # 오탐(닫힌 뚜껑/본체 평면) 게이트
    "closed_laptop_ar": 4.5,       # laptop bbox 자체가 매우 납작(w/h)하면 닫힘/측면 slab
    # 블러 강도(설정값) — 통합 엔진이 mask+feather로 적용
    "blur_kernel_ratio": 0.45,
    "blur_kernel_min": 25,
}

_COCO = {62: "tv", 63: "laptop"}
_CLAHE = cv2.createCLAHE(3.0, (8, 8))


def imread_u(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_u(path, img):
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)
    return ok


class YoloxDetector:
    def __init__(self, model_dir):
        o = ort.SessionOptions()
        o.log_severity_level = 3
        self.sess = ort.InferenceSession(os.path.join(model_dir, "yolox_s.onnx"),
                                         sess_options=o, providers=["CPUExecutionProvider"])
        self.inp = self.sess.get_inputs()[0].name

    def _preproc(self, img):
        S = CONFIG["yolox_input"]
        padded = np.ones((S, S, 3), dtype=np.uint8) * 114
        r = min(S / img.shape[0], S / img.shape[1])
        nh, nw = int(img.shape[0] * r), int(img.shape[1] * r)
        padded[:nh, :nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        blob = padded.transpose(2, 0, 1)[None].astype(np.float32)  # BGR, no norm, pad 114
        return blob, r

    @staticmethod
    def _decode(out, S):
        # out: [N,85] raw. grid decode (strides 8/16/32)
        grids, strides = [], []
        for st in (8, 16, 32):
            hs = ws = S // st
            xv, yv = np.meshgrid(np.arange(ws), np.arange(hs))
            grid = np.stack((xv, yv), 2).reshape(-1, 2)
            grids.append(grid)
            strides.append(np.full((grid.shape[0], 1), st))
        grids = np.concatenate(grids, 0)
        strides = np.concatenate(strides, 0)
        out[:, :2] = (out[:, :2] + grids) * strides
        out[:, 2:4] = np.exp(out[:, 2:4]) * strides
        return out

    @staticmethod
    def _nms(boxes, scores, thr):
        x1, y1, x2, y2 = boxes.T
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]; keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0, xx2 - xx1); h = np.maximum(0, yy2 - yy1)
            iou = (w * h) / (areas[i] + areas[order[1:]] - w * h + 1e-9)
            order = order[1:][iou <= thr]
        return keep

    def detect(self, img, want_classes):
        S = CONFIG["yolox_input"]
        blob, r = self._preproc(img)
        out = self.sess.run(None, {self.inp: blob})[0][0]  # [8400,85]
        out = self._decode(out.copy(), S)
        boxes = out[:, :4].copy()
        # cxcywh -> xyxy, back to original scale
        xyxy = np.empty_like(boxes)
        xyxy[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
        xyxy[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
        xyxy[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
        xyxy[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
        xyxy /= r
        obj = out[:, 4]
        cls_scores = out[:, 5:]
        cls_id = cls_scores.argmax(1)
        conf = obj * cls_scores.max(1)
        res = []
        for cid in want_classes:
            m = (cls_id == cid) & (conf >= CONFIG["det_conf"])
            if not m.any():
                continue
            b, s = xyxy[m], conf[m]
            for j in self._nms(b, s, CONFIG["nms_thr"]):
                x1, y1, x2, y2 = b[j]
                res.append({"bbox": [float(x1), float(y1), float(x2), float(y2)],
                            "score": float(s[j]), "cls": int(cid)})
        return res


# ── 화면 패널 추출 (내용-기반, cv2/numpy) ──
def extract_panel(roi):
    """laptop ROI 안에서 '내용(UI/텍스트) 있는 디스플레이' 영역을 찾아 (polygon, metrics) 반환.
    내용 화면은 CLAHE 엣지밀도·수평구조가 높다(밝든 어둡든). 균일 뚜껑/본체/어깨은 내용이 없어 제외.
    YOLOX bbox는 ROI 후보일 뿐 — 최종 블러 영역은 여기서 찾은 패널 polygon."""
    H, W = roi.shape[:2]
    area = float(H * W)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    cl = _CLAHE.apply(gray)
    edges = cv2.Canny(cl, 60, 160)
    k = max(7, (min(H, W) // 12) | 1)
    dens = cv2.boxFilter(edges.astype(np.float32) / 255, -1, (k, k))
    mask = (dens > CONFIG["content_dens_thr"]).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=1)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = max(cnts, key=cv2.contourArea, default=None)
    if best is None or cv2.contourArea(best) < CONFIG["panel_min_area_ratio"] * area:
        return None, None
    rect = cv2.minAreaRect(best)
    (rw, rh) = rect[1]
    long_, short_ = max(rw, rh), min(rw, rh)
    if short_ < 1 or long_ / (short_ + 1e-6) > CONFIG["panel_ar_max"]:
        return None, None
    box = cv2.boxPoints(rect).astype(np.float32)
    m = np.zeros((H, W), np.uint8)
    cv2.fillConvexPoly(m, box.astype(np.int32), 255)
    inside = m > 0
    n_in = max(1, int(inside.sum()))
    ed_in = float(edges[inside].mean() / 255)
    # 수평구조(텍스트줄/UI 바): 박스 영역에서 행별 가로 엣지 많은 행 비율
    sob = np.abs(cv2.Sobel(cl, cv2.CV_32F, 0, 1, ksize=3))
    x, y, w, h = cv2.boundingRect(box.astype(np.int32))
    sub = sob[max(0, y):y + h, max(0, x):x + w]
    h_struct = float((((sub > 60).mean(axis=1)) > 0.15).mean()) if sub.size else 0.0
    # 피부색(어깨/손) 비율
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    skinmask = (hsv[:, :, 0] < 25) & (hsv[:, :, 1] > 40) & (hsv[:, :, 1] < 180) & (hsv[:, :, 2] > 80)
    skin = float((skinmask & inside).sum() / n_in)
    # 색 다채로움(colorfulness): 화면은 색 있는 UI/내용, 뒷면/뚜껑(금속·회색)은 단색 → 분리 단서
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB).astype(np.float32)
    colf = float(np.sqrt(lab[:, :, 1][inside].std() ** 2 + lab[:, :, 2][inside].std() ** 2))
    return box, {"ed_in": round(ed_in, 3), "h_struct": round(h_struct, 3), "colf": round(colf, 1),
                 "skin": round(skin, 3), "area_ratio": round(cv2.contourArea(best) / area, 2),
                 "panel_ar": round(long_ / (short_ + 1e-6), 2)}


def _is_screen(mt):
    """내용 metrics -> 화면 여부 (내용 화면 vs 균일 뚜껑/본체/어깨/케이블-책상 strip).
    세 경로 중 하나면 화면: 수평구조(텍스트/UI줄) / 엣지밀도(내용 많음) / 색 다채로움(색 있는 UI).
    단, 패널이 지나치게 납작(wide-flat)하면 화면이 아님 — 화면 없이 베이스/키보드/케이블만 잡힌 경우."""
    if mt is None:
        return False
    if mt["skin"] > CONFIG["screen_skin_max"]:
        return False
    if mt.get("panel_ar", 1.0) > CONFIG["screen_panel_ar_max"]:   # 케이블/키보드/책상 strip 배제
        return False
    return (mt["h_struct"] >= CONFIG["screen_hstruct_min"]
            or mt["ed_in"] >= CONFIG["screen_ed_min"]
            or mt.get("colf", 0) >= CONFIG["screen_colf_min"])


def blur_polygon(img, pts):
    x, y, w, h = cv2.boundingRect(pts.astype(np.int32))
    k = max(CONFIG["blur_kernel_min"], int(max(w, h) * CONFIG["blur_kernel_ratio"]))
    k |= 1
    mask = np.zeros(img.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, pts.astype(np.int32), 255)
    blurred = cv2.GaussianBlur(img, (k, k), 0)
    out = img.copy()
    out[mask > 0] = blurred[mask > 0]
    return out


def run(img_dir, out_dir, model_dir):
    os.makedirs(out_dir, exist_ok=True)
    det = YoloxDetector(model_dir)
    files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    report = {"model": "yolox_s.onnx(Apache-2.0)", "config": CONFIG, "images": {}}
    tot_blur = tot_keep = 0
    for fn in files:
        img = imread_u(os.path.join(img_dir, fn))
        if img is None:
            continue
        dets = det.detect(img, [CONFIG["laptop_cls"], CONFIG["tv_cls"]])
        vis = img.copy()
        out_img = img.copy()
        regions = []
        for d in dets:
            x1, y1, x2, y2 = [int(round(v)) for v in d["bbox"]]
            x1, y1 = max(0, x1), max(0, y1); x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
            lw, lh = x2 - x1, y2 - y1
            if lw < 5 or lh < 5:
                continue
            cls_name = _COCO.get(d["cls"], str(d["cls"]))
            # tv/monitor 는 블러 대상 아님(기록만)
            if d["cls"] == CONFIG["tv_cls"]:
                regions.append({"type": "screen", "action": "keep", "method": "blur",
                                "source": "tv_monitor", "parent_laptop_bbox": [x1, y1, x2, y2],
                                "bbox": None, "confidence": round(d["score"], 3),
                                "reason": "external monitor/tv (not personal laptop)"})
                cv2.rectangle(vis, (x1, y1), (x2, y2), (128, 128, 128), 3)
                cv2.putText(vis, "tv keep", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (128, 128, 128), 2)
                continue
            cv2.rectangle(vis, (x1, y1), (x2, y2), (255, 160, 0), 3)  # laptop = 파랑
            # 닫힘/측면 slab 배제
            if max(lw, lh) < CONFIG["min_laptop_px"]:
                reason = "too_small"
                regions.append({"type": "screen", "action": "keep", "method": "blur", "source": "laptop_panel",
                                "parent_laptop_bbox": [x1, y1, x2, y2], "bbox": None,
                                "confidence": round(d["score"], 3), "reason": reason})
                cv2.putText(vis, "skip:small", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                continue
            if lw / (lh + 1e-6) >= CONFIG["closed_laptop_ar"]:
                reason = "closed_or_side_slab"
                regions.append({"type": "screen", "action": "keep", "method": "blur", "source": "laptop_panel",
                                "parent_laptop_bbox": [x1, y1, x2, y2], "bbox": None,
                                "confidence": round(d["score"], 3), "reason": reason})
                cv2.putText(vis, "skip:closed", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                continue
            roi = img[y1:y2, x1:x2]
            box, mt = extract_panel(roi)
            if box is None:
                regions.append({"type": "screen", "action": "keep", "method": "blur", "source": "laptop_panel",
                                "parent_laptop_bbox": [x1, y1, x2, y2], "bbox": None, "poly": None,
                                "confidence": round(d["score"], 3), "reason": "no_content_panel"})
                cv2.putText(vis, "no panel", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                continue
            pts_abs = box + np.array([x1, y1], np.float32)
            px, py, pw, ph = cv2.boundingRect(pts_abs.astype(np.int32))
            reason = f"h{mt['h_struct']}_ed{mt['ed_in']}_colf{mt['colf']}_c{d['score']:.2f}"
            is_scr = _is_screen(mt)
            # 저conf 약검출은 '색 있는 내용'만 화면으로 — 단색 금속뚜껑/키보드 오탐 배제(metric으론 구분 불가)
            if is_scr and d["score"] < CONFIG["low_conf_thr"] and mt["colf"] < CONFIG["low_conf_colf_min"]:
                is_scr = False
                reason = "lowconf_mono_" + reason
            if not is_scr:   # 내용 없는 균일 뚜껑/본체/어깨/저conf단색 -> 블러 안 함
                regions.append({"type": "screen", "action": "keep", "method": "blur", "source": "laptop_panel",
                                "parent_laptop_bbox": [x1, y1, x2, y2], "bbox": [px, py, px + pw, py + ph],
                                "poly": pts_abs.astype(int).tolist(),
                                "confidence": round(d["score"], 3), "reason": "low_content_" + reason})
                cv2.polylines(vis, [pts_abs.astype(np.int32)], True, (0, 0, 255), 2)
                cv2.putText(vis, "skip:lid", (x1, max(0, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                continue
            # --- 화면(내용 있음): 블러 대상. 최종 블러는 통합 엔진이 polygon+feather로 적용 ---
            out_img = blur_polygon(out_img, pts_abs)
            tot_blur += 1
            regions.append({"type": "screen", "action": "blur", "method": "blur", "source": "laptop_panel",
                            "parent_laptop_bbox": [x1, y1, x2, y2], "bbox": [px, py, px + pw, py + ph],
                            "poly": pts_abs.astype(int).tolist(),
                            "confidence": round(d["score"], 3), "reason": "content_" + reason})
            cv2.polylines(vis, [pts_abs.astype(np.int32)], True, (0, 0, 255), 3)  # 패널 = 빨강
            cv2.putText(vis, "screen blur", (px, max(0, py - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
        tot_keep += sum(1 for r in regions if r["action"] == "keep")
        imwrite_u(os.path.join(out_dir, "blur_" + fn), out_img)
        imwrite_u(os.path.join(out_dir, "vis_" + fn), vis)
        report["images"][fn] = {"laptops_detected": sum(1 for d in dets if d["cls"] == CONFIG["laptop_cls"]),
                                "tv_detected": sum(1 for d in dets if d["cls"] == CONFIG["tv_cls"]),
                                "blurred": sum(1 for r in regions if r["action"] == "blur"),
                                "regions": regions}
        nb = report["images"][fn]["blurred"]
        print(f"  {fn[-10:]}: laptop={report['images'][fn]['laptops_detected']} "
              f"tv={report['images'][fn]['tv_detected']} screen_blur={nb} "
              f"keep={sum(1 for r in regions if r['action']=='keep')}")
    with open(os.path.join(out_dir, "화면블러리포트.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[screen] 블러 {tot_blur} / keep {tot_keep}")
    print(f"[out] {os.path.join(out_dir, '화면블러리포트.json')}")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
