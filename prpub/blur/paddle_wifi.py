# -*- coding: utf-8 -*-
"""Wi-Fi 카드 판정 헬퍼 — pocr2 env(PaddleOCR 2.7)에서 실행.
입력: 카드 crop 이미지들이 있는 디렉터리. 출력: {key: {ran,net,cred,value,wifi}} JSON.
개인정보 비저장: SSID/PW 문자열을 어디에도 저장/출력하지 않고 플래그(net/cred/value)만 남긴다.
모델은 ASCII 경로(C:\\paddle_models) 사용 — 한글 사용자명 경로를 paddle C++가 못 열기 때문."""
import os, re, sys, json, warnings
warnings.filterwarnings("ignore")
import numpy as np, cv2

NET = ["wifi", "wi-fi", "wlan", "ssid", "와이파이", "무선", "network", "네트워크"]
CRED = ["password", "passwd", "비밀번호", "비번", "암호"]
PW = re.compile(r'\bpw\b')
VAL = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9._@#!\-:]{4,40}$')


def flags(t):
    tl = t.lower()
    return (("N" if any(k in tl for k in NET) else "")
            + ("C" if (any(k in tl for k in CRED) or PW.search(tl)) else "")
            + ("V" if VAL.match(t.strip()) else ""))


def main():
    crop_dir, out_json = sys.argv[1], sys.argv[2]
    models = os.environ.get("DAEASY_PADDLE_MODELS", r"C:\paddle_models")
    from paddleocr import PaddleOCR
    # en + korean 두 인식기 — 합집합으로 라벨 누락 보완(영문 'PW' / 한글 '비밀번호' 모두 대응)
    ocr_en = PaddleOCR(use_angle_cls=False, lang='en', show_log=False,
                       det_model_dir=os.path.join(models, "det", "en", "en_PP-OCRv3_det_infer"),
                       rec_model_dir=os.path.join(models, "rec", "en", "en_PP-OCRv4_rec_infer"))
    ocr_ko = PaddleOCR(use_angle_cls=False, lang='korean', show_log=False,
                       det_model_dir=os.path.join(models, "det", "ml", "Multilingual_PP-OCRv3_det_infer"),
                       rec_model_dir=os.path.join(models, "rec", "korean", "korean_PP-OCRv4_rec_infer"))
    res = {}
    for fn in sorted(os.listdir(crop_dir)):
        if not fn.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        key = os.path.splitext(fn)[0]
        im = cv2.imdecode(np.fromfile(os.path.join(crop_dir, fn), np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            res[key] = {"ran": True, "net": False, "cred": False, "value": False, "wifi": False}
            continue
        hasN = hasC = hasV = False
        for ocr in (ocr_en, ocr_ko):
            for fx in (1, 2):                  # 원본 + 2× (작은 글자 보강)
                img = im if fx == 1 else cv2.resize(im, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                r = ocr.ocr(img, cls=False)
                lines = r[0] if (r and r[0]) else []
                for _, (t, c) in lines:
                    if c < 0.3:
                        continue
                    f = flags(t)
                    hasN |= "N" in f; hasC |= "C" in f; hasV |= "V" in f
                # 문자열 t 는 여기서 폐기 — 저장/출력하지 않음
        wifi = (hasN and hasC) or (hasC and hasV)
        res[key] = {"ran": True, "net": hasN, "cred": hasC, "value": hasV, "wifi": wifi}
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f)
    print("OK cards=%d" % len(res))


if __name__ == "__main__":
    main()
