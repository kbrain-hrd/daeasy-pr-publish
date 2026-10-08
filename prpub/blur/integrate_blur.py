# -*- coding: utf-8 -*-
"""
최종 통합: face + screen + wifi -> region 통합 -> 원본에서 1회 Gaussian Blur -> 강사 keep 복원.

- 검증 끝난 각 모듈(face_blur / screen_blur / wifi_blur)의 '검출 로직'은 수정하지 않는다.
  각 모듈의 run()을 그대로 호출해 리포트(region)를 받고, 이 통합 모듈이 '원본 1장'에
  모든 블러를 한 번만 적용한 뒤 강사(instructor keep) 영역을 원본에서 복원한다.
- 좌표계: 세 모듈 모두 원본 이미지 픽셀 좌표로 bbox를 보고 -> 그대로 통합.
- 블러는 항상 '원본 픽셀'에서 계산해 겹침 영역이라도 Gaussian이 중복 적용되지 않는다(1회).
- keep(강사)은 블러를 모두 적용한 뒤 마지막에 원본에서 복원 -> 어떤 블러와 겹쳐도 강사 얼굴 유지.
- 개인정보 문자열(SSID/PW/QR 내용)은 저장하지 않는다(각 모듈 리포트가 이미 비저장).
"""
import os, sys, json, shutil, tempfile, importlib.util
import numpy as np
import cv2

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

FB = _load("face_blur")
SB = _load("screen_blur")
WB = _load("wifi_blur")

imread_u, imwrite_u = FB.imread_u, FB.imwrite_u


def _odd(k):
    k = int(max(3, k))
    return k | 1


def _shape_mask(H, W, r):
    """region -> 바이너리 mask. face=타원 soft mask, screen/wifi=polygon, 그 외=bbox 사각형."""
    m = np.zeros((H, W), np.uint8)
    if r["type"] == "face":
        x1, y1, x2, y2 = r["bbox"]
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        ax = (x2 - x1) / 2.0 * 1.15
        ay = (y2 - y1) / 2.0 * 1.30          # 이마/턱 포함 자연스러운 얼굴 타원
        cv2.ellipse(m, (int(round(cx)), int(round(cy))), (int(round(ax)), int(round(ay))),
                    0, 0, 360, 255, -1)
    elif r.get("poly"):
        cv2.fillConvexPoly(m, np.array(r["poly"], np.int32), 255)
    else:
        x1, y1, x2, y2 = [int(round(v)) for v in r["bbox"]]
        cv2.rectangle(m, (max(0, x1), max(0, y1)), (min(W, x2), min(H, y2)), 255, -1)
    return m


def _feather_blur(out, orig, mask, kmin, kratio, feather_ratio):
    """mask(255 내부)을 원본에서 강한 Gaussian + 가장자리 feathering 으로 합성.
    out = out*(1-alpha) + blur*alpha  (alpha=페더링된 soft mask). 사각형 경계가 남지 않는다."""
    ys, xs = np.where(mask > 0)
    if ys.size == 0:
        return
    H, W = orig.shape[:2]
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    mw, mh = x2 - x1, y2 - y1
    feat = _odd(max(5, int(max(mw, mh) * feather_ratio)))
    pad = feat
    rx1, ry1 = max(0, x1 - pad), max(0, y1 - pad)
    rx2, ry2 = min(W, x2 + pad), min(H, y2 + pad)
    k = _odd(max(kmin, int(max(mw, mh) * kratio)))
    roi_b = cv2.GaussianBlur(orig[ry1:ry2, rx1:rx2], (k, k), 0)
    alpha = cv2.GaussianBlur(mask[ry1:ry2, rx1:rx2].astype(np.float32) / 255.0, (feat, feat), 0)
    alpha = np.clip(alpha, 0.0, 1.0)[:, :, None]
    out[ry1:ry2, rx1:rx2] = (out[ry1:ry2, rx1:rx2] * (1 - alpha) + roi_b * alpha).astype(np.uint8)


def collect_regions(face_rep, screen_rep, wifi_rep, fn):
    """세 모듈 리포트에서 한 이미지의 통합 region 목록 생성 (shape 정보 poly 포함)."""
    regions = []
    for f in face_rep.get(fn, {}).get("faces", []):
        role = f["role"]
        if role == "excluded":
            continue
        regions.append({"type": "face", "bbox": [float(v) for v in f["bbox"]],
                        "action": "keep" if role == "instructor_kept" else "blur",
                        "method": "blur", "confidence": float(f.get("score", 0.0)),
                        "reason": role, "cluster": f.get("cluster")})
    for r in screen_rep.get(fn, {}).get("regions", []):
        if r.get("bbox") is None:
            continue
        regions.append({"type": "screen", "bbox": [float(v) for v in r["bbox"]], "poly": r.get("poly"),
                        "action": r["action"], "method": "blur", "confidence": float(r.get("confidence", 0.0)),
                        "reason": r.get("reason", ""), "source": r.get("source", "")})
    for r in wifi_rep.get(fn, {}).get("regions", []):
        if r.get("bbox") is None:
            continue
        regions.append({"type": "wifi", "bbox": [float(v) for v in r["bbox"]], "poly": r.get("poly"),
                        "action": r["action"], "method": "blur", "confidence": float(r.get("confidence", 0.0)),
                        "reason": r.get("reason", ""), "source": r.get("source", "")})
    return regions


def apply_regions(orig, regions):
    """mask+feather 로 blur 합성(사각형 bbox 블러 아님) -> 강사(face keep) 타원 영역 원본 복원."""
    out = orig.copy()
    H, W = orig.shape[:2]
    FEAT = 0.22
    for r in regions:
        if r["action"] != "blur":
            continue
        mask = _shape_mask(H, W, r)
        if r["type"] == "face":
            kmin, kratio = FB.CONFIG["blur_kernel_min"], max(0.5, FB.CONFIG["blur_kernel_ratio"])
        elif r["type"] == "screen":
            kmin, kratio = SB.CONFIG["blur_kernel_min"], SB.CONFIG["blur_kernel_ratio"]
        else:
            kmin, kratio = WB.CONFIG["blur_kernel_min"], WB.CONFIG["blur_kernel_ratio"]
        _feather_blur(out, orig, mask, kmin, kratio, FEAT)
    # 강사(face keep): 타원 영역을 원본에서 복원 — 최종 우선순위(어떤 블러와 겹쳐도 샤프 유지)
    for r in regions:
        if r["type"] == "face" and r["action"] == "keep":
            m = _shape_mask(H, W, r)
            out[m > 0] = orig[m > 0]
    return out


def _draw(vis, regions):
    col = {("face", "blur"): (0, 0, 255), ("face", "keep"): (0, 200, 0),
           ("screen", "blur"): (255, 160, 0), ("screen", "keep"): (160, 160, 160),
           ("wifi", "blur"): (255, 0, 255), ("wifi", "keep"): (160, 160, 160)}
    for r in regions:
        x1, y1, x2, y2 = [int(round(v)) for v in r["bbox"]]
        c = col.get((r["type"], r["action"]), (200, 200, 200))
        cv2.rectangle(vis, (x1, y1), (x2, y2), c, 3)
        cv2.putText(vis, f"{r['type']}:{r['action']}", (x1, max(0, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, c, 2)


def run(img_dir, out_dir, model_dir, do_wifi=True):
    os.makedirs(out_dir, exist_ok=True)
    img_final = os.path.join(out_dir, "images")
    img_orig = os.path.join(img_final, "원본")
    os.makedirs(img_orig, exist_ok=True)

    # 1) 각 모듈을 그대로 실행해 리포트(region) 확보 (검출 로직 미수정)
    print("=== face 모듈 ===")
    FB.run_event(img_dir, os.path.join(out_dir, "_face"), model_dir)
    print("=== screen 모듈 ===")
    SB.run(img_dir, os.path.join(out_dir, "_screen"), model_dir)
    if do_wifi:
        print("=== wifi 모듈 ===")
        WB.run(img_dir, os.path.join(out_dir, "_wifi"))

    face_rep = json.load(open(os.path.join(out_dir, "_face", "블러리포트.json"), encoding="utf-8"))["images"]
    screen_rep = json.load(open(os.path.join(out_dir, "_screen", "화면블러리포트.json"), encoding="utf-8"))["images"]
    wifi_rep = (json.load(open(os.path.join(out_dir, "_wifi", "wifi블러리포트.json"), encoding="utf-8"))["images"]
                if do_wifi else {})

    files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    report = {"pipeline": "face+screen+wifi -> unified regions -> single blur -> instructor keep restore",
              "privacy": "no SSID/password/QR content stored", "images": {}}
    issues = []
    for fn in files:
        orig = imread_u(os.path.join(img_dir, fn))
        if orig is None:
            continue
        regions = collect_regions(face_rep, screen_rep, wifi_rep, fn)
        final = apply_regions(orig, regions)

        imwrite_u(os.path.join(img_orig, fn), orig)
        imwrite_u(os.path.join(img_final, fn), final)
        imwrite_u(os.path.join(out_dir, "blur_" + fn), final)
        vis = final.copy(); _draw(vis, regions)
        imwrite_u(os.path.join(out_dir, "vis_" + fn), vis)

        nb = {"face": 0, "screen": 0, "wifi": 0}
        nk = 0
        for r in regions:
            if r["action"] == "blur":
                nb[r["type"]] += 1
            elif r["type"] == "face":
                nk += 1
        # 교차검증: 강사(keep) 타원 영역이 최종 이미지에서 원본과 동일(복원됨)한지
        instr_ok = True
        H0, W0 = orig.shape[:2]
        for r in regions:
            if r["type"] == "face" and r["action"] == "keep":
                m = _shape_mask(H0, W0, r)
                if (m > 0).any() and not np.array_equal(final[m > 0], orig[m > 0]):
                    instr_ok = False
                    issues.append(f"{fn}: instructor keep not restored")
        report["images"][fn] = {"regions": regions,
                                 "blur_face": nb["face"], "blur_screen": nb["screen"],
                                 "blur_wifi": nb["wifi"], "keep_instructor": nk,
                                 "instructor_restored": instr_ok}
        print(f"  {fn[-10:]}: face_blur={nb['face']} screen_blur={nb['screen']} "
              f"wifi_blur={nb['wifi']} instructor_keep={nk} restored={instr_ok}")

    report["validation"] = {"instructor_all_restored": len(issues) == 0, "issues": issues,
                            "blur_method": "gaussian"}
    with open(os.path.join(out_dir, "블러리포트.json"), "w", encoding="utf-8") as w:
        json.dump(report, w, ensure_ascii=False, indent=2)
    print(f"[integrate] 강사 복원 검증={len(issues)==0} issues={issues}")
    print(f"[out] images/={img_final}  원본={img_orig}  report={os.path.join(out_dir,'블러리포트.json')}")


_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")


def preprocess_images_inplace(images_dir, model_dir, do_wifi=True):
    """prpub build 연결용: images_dir 안의 사진을 제자리에서 개인정보 블러.
      1) 원본을 images_dir/원본/ 로 보존
      2) 원본을 대상으로 face+screen+wifi region 산출(mask+feather)
      3) 블러본으로 images_dir/<같은이름> 덮어쓰기 (파일명/순서 불변)
    실패 시 예외를 올린다(블러 실패분이 조용히 다운스트림으로 가지 않도록)."""
    images_dir = os.path.abspath(images_dir)
    orig_dir = os.path.join(images_dir, "원본")
    names = sorted(f for f in os.listdir(images_dir)
                   if os.path.isfile(os.path.join(images_dir, f))
                   and os.path.splitext(f)[1].lower() in _IMG_EXT)
    if not names:
        print("[blur] 처리할 이미지 없음")
        return {"total": 0, "blurred": 0, "skipped": []}
    os.makedirs(orig_dir, exist_ok=True)
    for n in names:
        shutil.copy2(os.path.join(images_dir, n), os.path.join(orig_dir, n))

    work = tempfile.mkdtemp(prefix="daeasy_blur_")
    try:
        FB.run_event(orig_dir, os.path.join(work, "_face"), model_dir)
        SB.run(orig_dir, os.path.join(work, "_screen"), model_dir)
        if do_wifi:
            WB.run(orig_dir, os.path.join(work, "_wifi"))
        face_rep = json.load(open(os.path.join(work, "_face", "블러리포트.json"), encoding="utf-8"))["images"]
        screen_rep = json.load(open(os.path.join(work, "_screen", "화면블러리포트.json"), encoding="utf-8"))["images"]
        wifi_rep = (json.load(open(os.path.join(work, "_wifi", "wifi블러리포트.json"), encoding="utf-8"))["images"]
                    if do_wifi else {})
        report = {"pipeline": "face+screen+wifi -> unified regions -> mask+feather blur -> instructor keep restore",
                  "privacy": "no SSID/password/QR content stored", "images": {}}
        issues, skipped, nblur = [], [], 0
        for n in names:
            orig = imread_u(os.path.join(orig_dir, n))
            if orig is None:
                skipped.append(n)
                print(f"[blur][경고] {n} 디코드 불가 → 블러 생략(원본 보존됨, 최종물 사용 주의)")
                continue
            regions = collect_regions(face_rep, screen_rep, wifi_rep, n)
            final = apply_regions(orig, regions)
            imwrite_u(os.path.join(images_dir, n), final)
            nblur += 1
            instr_ok = True
            H0, W0 = orig.shape[:2]
            for r in regions:
                if r["type"] == "face" and r["action"] == "keep":
                    m = _shape_mask(H0, W0, r)
                    if (m > 0).any() and not np.array_equal(final[m > 0], orig[m > 0]):
                        instr_ok = False
                        issues.append(f"{n}: instructor keep not restored")
            report["images"][n] = {"regions": regions, "instructor_restored": instr_ok}
        report["validation"] = {"instructor_all_restored": len(issues) == 0,
                                "issues": issues, "blur_method": "gaussian_mask_feather",
                                "skipped_undecodable": skipped}
        with open(os.path.join(images_dir, "블러리포트.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[blur] 완료: 블러본 {nblur}/{len(names)}  원본보존={orig_dir}  "
              f"강사복원={len(issues)==0}  미디코드={len(skipped)}")
        return {"total": len(names), "blurred": nblur, "skipped": skipped,
                "instructor_all_restored": len(issues) == 0}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preprocess":
        wifi = not (len(sys.argv) > 4 and sys.argv[4] == "nowifi")
        preprocess_images_inplace(sys.argv[2], sys.argv[3], do_wifi=wifi)
    else:
        wifi = not (len(sys.argv) > 4 and sys.argv[4] == "nowifi")
        run(sys.argv[1], sys.argv[2], sys.argv[3], do_wifi=wifi)
