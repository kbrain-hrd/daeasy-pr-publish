"""얼굴 자동 블러 모듈 (1단계) — 독립 실행/테스트 프로토타입.

SCRFD(det_500m) + ArcFace(w600k_mbf) ONNX를 onnxruntime로 직접 실행.
전처리·얼굴정렬·임베딩·클러스터링·강사추정·모자이크 블러를 numpy/cv2/scipy로 처리.
- 노트북/Wi-Fi 블러는 포함하지 않음(1단계 얼굴만).
- 저장소/파이프라인에 연결하지 않음(독립). 모델은 ~/.daeasy/models/.
- 합의된 얼굴 처리 흐름: 검출→임베딩→클러스터→실제얼굴판별→강사추정→교육생 블러.
- 강사 reference·수동 UI 없음. 강사 추정은 사진 전체를 묶어 자동.
- 파라미터는 CONFIG로 분리(하드코딩 금지). 블러는 모자이크(블록 크기 설정값).

주의(미완/후속 단계 필요):
- '서 있는 자세'(w_standing)와 '신체 연결/화면·포스터 배제'는 포즈·화면 검출 모델이
  있어야 가능 → 현재는 비활성(0)·PENDING으로 표시. 얼굴 신호(반복·정면·크기·위치)만 사용.
"""
import os, sys, json, math
import numpy as np
import cv2
import onnxruntime as ort
from scipy.cluster.hierarchy import linkage, fcluster

# ──────────────────────────── 설정값(분리) ────────────────────────────
CONFIG = {
    "det_input": 1280,           # SCRFD 입력 정사각 크기 (↑ 와이드샷 작은 얼굴 검출/연결 개선 — ⓑ)
    "det_score_thr": 0.45,       # 얼굴 검출 점수 임계
    "nms_thr": 0.4,              # NMS IoU 임계
    "min_face_px": 18,           # 이보다 작은 얼굴은 제외(최소 변)
    "cluster_cos_dist": 0.55,    # 동일 인물 병합 임계(코사인 거리; 작을수록 엄격)
    "instructor": {
        "w_recurrence": 1.0,     # 여러 사진 반복 등장(주 신호)
        "w_frontal":    0.6,     # 정면/카메라 응시
        "w_size":       0.4,     # 얼굴 크기(가까움/강조)
        "w_vpos":       0.3,     # 화면 내 위치(위쪽=서있는 강사 경향)
        "w_standing":   0.0,     # 포즈 모델 추가 시 활성 (현재 미사용)
        "min_confidence": 0.40,  # 이 미만이면 강사 보호 안 함 → 불확실 기록
        "min_margin":     0.12,  # 1·2위 점수차 최소(모호하면 보호 안 함)
    },
    "face_pad": 0.18,            # 마스킹 시 얼굴 영역 확장 비율
    # 마스킹 방식 — 요구사항은 '블러'(가우시안). 기본 blur. (mosaic은 옵션으로만)
    "mask_method": "blur",       # "blur"(가우시안, 기본) | "mosaic"
    "blur_kernel_ratio": 0.60,   # 가우시안 커널 = 얼굴 긴변 * 비율 (설정값, 원본 확보 후 조정)
    "blur_kernel_min": 15,       # 커널 최소 px (홀수화)
    "mosaic_block_ratio": 0.10,  # (옵션) 모자이크 블록 = 얼굴폭 * 비율
    "mosaic_block_min": 6,
}

# ArcFace 표준 5점(112x112) — 정렬 기준
_ARCFACE_REF = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)

_STRIDES = [8, 16, 32]
_NUM_ANCHORS = 2


def imread_u(path):
    """유니코드 경로 안전 읽기."""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_u(path, img):
    ext = os.path.splitext(path)[1] or ".jpg"
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)


class FaceEngine:
    def __init__(self, model_dir):
        o = ort.SessionOptions()
        o.log_severity_level = 3  # det_500m 출력 shape가 640 기준 정적선언이라, 해상도 변경 시
        #                           나오는 VerifyOutputSizes 경고(계산엔 무해) 억제
        self.det = ort.InferenceSession(os.path.join(model_dir, "det_500m.onnx"),
                                        sess_options=o, providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(os.path.join(model_dir, "w600k_mbf.onnx"),
                                        sess_options=o, providers=["CPUExecutionProvider"])
        self.det_in = self.det.get_inputs()[0].name
        self.rec_in = self.rec.get_inputs()[0].name
        self._centers = {}

    # ── SCRFD 검출 ──
    def detect(self, img):
        S = CONFIG["det_input"]
        h, w = img.shape[:2]
        scale = S / max(h, w)
        nw, nh = int(round(w * scale)), int(round(h * scale))
        canvas = np.zeros((S, S, 3), dtype=np.uint8)
        canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128, (S, S),
                                     (127.5, 127.5, 127.5), swapRB=True)
        outs = self.det.run(None, {self.det_in: blob})
        scores_l, bbox_l, kps_l = outs[0:3], outs[3:6], outs[6:9]
        boxes, scs, kpss = [], [], []
        for i, stride in enumerate(_STRIDES):
            sc = scores_l[i].reshape(-1)
            bb = bbox_l[i].reshape(-1, 4) * stride
            kp = kps_l[i].reshape(-1, 10) * stride
            fw = fh = S // stride
            key = (fh, fw, stride)
            if key not in self._centers:
                ax, ay = np.meshgrid(np.arange(fw), np.arange(fh))
                c = np.stack([ax, ay], -1).astype(np.float32).reshape(-1, 2) * stride
                self._centers[key] = np.repeat(c, _NUM_ANCHORS, axis=0)
            c = self._centers[key]
            keep = sc >= CONFIG["det_score_thr"]
            if not keep.any():
                continue
            cc, bbp, kpp, scp = c[keep], bb[keep], kp[keep], sc[keep]
            b = np.stack([cc[:, 0] - bbp[:, 0], cc[:, 1] - bbp[:, 1],
                          cc[:, 0] + bbp[:, 2], cc[:, 1] + bbp[:, 3]], axis=1)
            k = kpp.reshape(-1, 5, 2) + cc[:, None, :]
            boxes.append(b); scs.append(scp); kpss.append(k)
        if not boxes:
            return []
        boxes = np.concatenate(boxes) / scale
        kpss = np.concatenate(kpss) / scale
        scs = np.concatenate(scs)
        keep = self._nms(boxes, scs)
        res = []
        for j in keep:
            x1, y1, x2, y2 = boxes[j]
            if min(x2 - x1, y2 - y1) < CONFIG["min_face_px"]:
                continue
            res.append({"bbox": [float(x1), float(y1), float(x2), float(y2)],
                        "score": float(scs[j]), "kps": kpss[j].astype(np.float32)})
        return res

    @staticmethod
    def _nms(boxes, scores):
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]; keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]]); yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]]); yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0, xx2 - xx1); h = np.maximum(0, yy2 - yy1)
            iou = (w * h) / (areas[i] + areas[order[1:]] - w * h + 1e-9)
            order = order[1:][iou <= CONFIG["nms_thr"]]
        return keep

    # ── ArcFace 임베딩 ──
    def embed(self, img, kps):
        M, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), _ARCFACE_REF,
                                           method=cv2.LMEDS)
        if M is None:
            return None
        face = cv2.warpAffine(img, M, (112, 112), borderValue=0.0)
        blob = cv2.dnn.blobFromImage(face, 1.0 / 127.5, (112, 112),
                                     (127.5, 127.5, 127.5), swapRB=True)
        e = self.rec.run(None, {self.rec_in: blob})[0].reshape(-1)
        n = np.linalg.norm(e)
        return e / (n + 1e-9) if n > 0 else None


# ── 보조 계산 ──
def frontal_score(kps):
    """정면성(0~1): 눈-코 좌우대칭 + 눈이 입보다 위."""
    le, re, no, lm, rm = kps
    dl = no[0] - le[0]; dr = re[0] - no[0]
    if dl <= 0 or dr <= 0:
        return 0.0
    sym = 1.0 - abs(dl - dr) / (dl + dr + 1e-6)
    upright = 1.0 if (le[1] < lm[1] and re[1] < rm[1]) else 0.3
    return max(0.0, min(1.0, sym * upright))


def is_real_face_face_only(f, img_shape):
    """1단계(얼굴 모델만)로 가능한 실제-얼굴 1차 판별.
    신체연결·화면/포스터 배제는 포즈·화면 검출 단계 필요 → PENDING."""
    x1, y1, x2, y2 = f["bbox"]
    w, h = x2 - x1, y2 - y1
    if min(w, h) < CONFIG["min_face_px"]:
        return False, "too_small"
    le, re, no, lm, rm = f["kps"]
    if not (le[1] < lm[1] and re[1] < rm[1]):   # 눈이 입보다 아래면 비정상(평면·오검출 의심)
        return False, "landmark_implausible"
    return True, "ok"


def _expand(box, W, H, pad):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    pw, ph = int((x2 - x1) * pad), int((y2 - y1) * pad)
    return max(0, x1 - pw), max(0, y1 - ph), min(W, x2 + pw), min(H, y2 + ph)


def apply_mask(img, box):
    """얼굴 영역 마스킹 — 기본 가우시안 블러(요구사항), 옵션 모자이크. (설정값 기반)"""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = _expand(box, W, H, CONFIG["face_pad"])
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    if CONFIG["mask_method"] == "mosaic":
        block = max(CONFIG["mosaic_block_min"], int((x2 - x1) * CONFIG["mosaic_block_ratio"]))
        small = cv2.resize(roi, (max(1, (x2 - x1) // block), max(1, (y2 - y1) // block)),
                           interpolation=cv2.INTER_AREA)
        img[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)
    else:  # 가우시안 블러(기본)
        k = max(CONFIG["blur_kernel_min"], int(max(x2 - x1, y2 - y1) * CONFIG["blur_kernel_ratio"]))
        k = k if k % 2 == 1 else k + 1
        img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


# ── 강사 추정(사진 전체 묶음) ──
def estimate_instructor(clusters, faces_by_cluster, img_h):
    ic = CONFIG["instructor"]
    rows = []
    for cid, members in faces_by_cluster.items():
        recurrence = len(set(m["img"] for m in members))
        frontal = np.mean([frontal_score(m["kps"]) for m in members])
        size = np.mean([(m["bbox"][2] - m["bbox"][0]) * (m["bbox"][3] - m["bbox"][1]) for m in members])
        vpos = np.mean([1.0 - ((m["bbox"][1] + m["bbox"][3]) / 2.0) / img_h for m in members])
        rows.append([cid, recurrence, frontal, size, vpos])
    if not rows:
        return None, 0.0, 0.0, []
    arr = np.array([[r[1], r[2], r[3], r[4]] for r in rows], dtype=np.float64)

    def norm(col):
        c = arr[:, col]
        rng = c.max() - c.min()
        return (c - c.min()) / rng if rng > 1e-9 else np.ones_like(c)
    score = (ic["w_recurrence"] * norm(0) + ic["w_frontal"] * norm(1) +
             ic["w_size"] * norm(2) + ic["w_vpos"] * norm(3))
    wsum = ic["w_recurrence"] + ic["w_frontal"] + ic["w_size"] + ic["w_vpos"]
    score = score / (wsum + 1e-9)
    order = score.argsort()[::-1]
    top = order[0]
    conf = float(score[top])
    margin = float(score[top] - (score[order[1]] if len(order) > 1 else 0.0))
    detail = [{"cluster": int(rows[i][0]), "recurrence": int(rows[i][1]),
               "frontal": round(float(rows[i][2]), 3), "score": round(float(score[i]), 3)}
              for i in order]
    protect = (conf >= ic["min_confidence"] and margin >= ic["min_margin"])
    return (int(rows[top][0]) if protect else None), conf, margin, detail


# ── 이벤트(한 교육 건) 처리 ──
def run_event(img_dir, out_dir, model_dir):
    os.makedirs(out_dir, exist_ok=True)
    eng = FaceEngine(model_dir)
    exts = (".jpg", ".jpeg", ".png")
    files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(exts))
    all_faces = []          # 전 사진 얼굴(임베딩 포함)
    per_img = {}            # img -> list(face idx)
    img_h_ref = None
    for fn in files:
        img = imread_u(os.path.join(img_dir, fn))
        if img is None:
            continue
        if img_h_ref is None:
            img_h_ref = img.shape[0]
        dets = eng.detect(img)
        per_img[fn] = []
        for d in dets:
            real, reason = is_real_face_face_only(d, img.shape)
            emb = eng.embed(img, d["kps"]) if real else None
            idx = len(all_faces)
            all_faces.append({"img": fn, "bbox": d["bbox"], "score": d["score"],
                              "kps": d["kps"], "real": real, "reason": reason,
                              "emb": emb})
            per_img[fn].append(idx)

    # 클러스터링(실제 얼굴만)
    real_idx = [i for i, f in enumerate(all_faces) if f["real"] and f["emb"] is not None]
    labels = {}
    if len(real_idx) == 1:
        labels[real_idx[0]] = 1
    elif len(real_idx) >= 2:
        embs = np.stack([all_faces[i]["emb"] for i in real_idx])
        Z = linkage(embs, method="average", metric="cosine")
        fl = fcluster(Z, t=CONFIG["cluster_cos_dist"], criterion="distance")
        for i, c in zip(real_idx, fl):
            labels[i] = int(c)
    for i, f in enumerate(all_faces):
        f["cluster"] = labels.get(i, None)

    faces_by_cluster = {}
    for i in real_idx:
        faces_by_cluster.setdefault(all_faces[i]["cluster"], []).append(all_faces[i])
    instr_cluster, conf, margin, detail = estimate_instructor(
        None, faces_by_cluster, img_h_ref or 1000)
    ambiguous = instr_cluster is None

    # 사진별 블러 적용 + 시각화 + 리포트
    report = {"event": os.path.basename(img_dir.rstrip("/\\")),
              "config": CONFIG,
              "instructor": {"cluster": instr_cluster, "confidence": round(conf, 3),
                             "margin": round(margin, 3), "ambiguous": ambiguous,
                             "candidates": detail},
              "pending": ["서있는자세(포즈 모델)", "신체연결·화면/포스터 배제(포즈·화면 검출)"],
              "images": {}}
    for fn in files:
        orig = imread_u(os.path.join(img_dir, fn))
        if orig is None:
            continue
        img = orig.copy()
        recs, blur_boxes, keep_boxes = [], [], []
        n_blur = n_keep = n_excl = 0
        for idx in per_img.get(fn, []):
            f = all_faces[idx]
            if not f["real"]:
                role = "excluded"; n_excl += 1
            elif f["cluster"] == instr_cluster and instr_cluster is not None:
                role = "instructor_kept"; n_keep += 1; keep_boxes.append(f["bbox"])
            else:
                role = "ambiguous_blur" if ambiguous else "student_blur"
                blur_boxes.append(f["bbox"]); n_blur += 1
            recs.append({"bbox": [round(v, 1) for v in f["bbox"]], "score": round(f["score"], 3),
                         "cluster": f["cluster"], "role": role, "reason": f["reason"]})
        # 1) 블러 대상에 마스킹(가우시안)
        for b in blur_boxes:
            apply_mask(img, b)
        # 2) 강사(유지) 얼굴 영역은 원본에서 복원 — 인접 블러 패딩에 겹쳐 가려지는 것을 방지,
        #    강사로 판정된 얼굴은 최종 출력에서 절대 블러되지 않도록 보장(ID/좌표 일치).
        H, W = img.shape[:2]
        for b in keep_boxes:
            x1, y1, x2, y2 = [int(round(v)) for v in b]
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(W, x2), min(H, y2)
            if x2 > x1 and y2 > y1:
                img[y1:y2, x1:x2] = orig[y1:y2, x1:x2]
        imwrite_u(os.path.join(out_dir, f"blur_{fn}"), img)
        # 시각화: 최종 결과 위에 역할별 박스
        vis = img.copy()
        colmap = {"instructor_kept": (0, 200, 0), "student_blur": (0, 0, 255),
                  "ambiguous_blur": (0, 220, 220), "excluded": (180, 180, 180)}
        for r in recs:
            x1, y1, x2, y2 = [int(v) for v in r["bbox"]]
            col = colmap[r["role"]]
            cv2.rectangle(vis, (x1, y1), (x2, y2), col, 3)
            cv2.putText(vis, f"{r['role'][:4]} c{r['cluster']}", (x1, max(0, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
        imwrite_u(os.path.join(out_dir, f"vis_{fn}"), vis)
        report["images"][fn] = {"faces_detected": len(per_img.get(fn, [])),
                                "blurred": n_blur, "kept_instructor": n_keep,
                                "excluded_nonface": n_excl,
                                "mask_method": CONFIG["mask_method"], "faces": recs}

    # ── 교차검증: 리포트 역할 ↔ 처리 대상 일치 (강사 cluster 얼굴이 블러 대상에 들어갔는지) ──
    issues = []
    for fn, v in report["images"].items():
        for r in v["faces"]:
            if (r["cluster"] == instr_cluster and instr_cluster is not None
                    and r["role"] != "instructor_kept"):
                issues.append(f"{fn}: 강사 cluster {r['cluster']} 얼굴 role={r['role']}")
    report["validation"] = {"mask_method": CONFIG["mask_method"],
                            "instructor_faces_all_kept": len(issues) == 0,
                            "issues": issues}

    with open(os.path.join(out_dir, "블러리포트.json"), "w", encoding="utf-8") as w:
        json.dump(report, w, ensure_ascii=False, indent=2,
                  default=lambda o: o.tolist() if isinstance(o, np.ndarray) else o)
    # 콘솔 요약
    print(f"[event] {report['event']}  사진 {len(files)}장  실제얼굴 {len(real_idx)}  "
          f"클러스터 {len(faces_by_cluster)}")
    print(f"[instructor] cluster={instr_cluster} conf={conf:.3f} margin={margin:.3f} "
          f"ambiguous={ambiguous}")
    for d in detail:
        print(f"   cand cluster {d['cluster']}: recurrence={d['recurrence']} "
              f"frontal={d['frontal']} score={d['score']}")
    tot_b = sum(v["blurred"] for v in report["images"].values())
    tot_k = sum(v["kept_instructor"] for v in report["images"].values())
    print(f"[blur] 방식={CONFIG['mask_method']}  블러 {tot_b} / 강사유지 {tot_k}")
    print(f"[validate] 강사얼굴 블러혼입 없음={report['validation']['instructor_faces_all_kept']}  "
          f"issues={report['validation']['issues']}")
    print(f"[out] {out_dir}\\블러리포트.json")


if __name__ == "__main__":
    img_dir, out_dir, model_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    run_event(img_dir, out_dir, model_dir)
