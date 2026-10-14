"""개인정보 블러 전처리 연결 (prpub .venv에서 실행).

prpub .venv에는 cv2/onnxruntime/easyocr가 없으므로, 블러는 그 의존성이 설치된
별도 파이썬(conda pro1)으로 서브프로세스 실행한다. images_dir 안에서 제자리로
  원본 → images/원본/,  블러본 → images/<같은이름>
처리한다(파일명·순서 불변). 블러에 실패하면 예외를 올려(fail-closed) 블러 안 된
원본이 조용히 다운스트림으로 가지 않게 한다.

환경변수:
  DAEASY_BLUR          "0" 이면 전처리를 건너뛴다(명시적 opt-out).
  DAEASY_BLUR_PYTHON   블러 실행 파이썬 경로(기본: C:\\conda\\envs\\pro1\\python.exe)
  DAEASY_BLUR_MODELS   onnx 모델 디렉터리(기본: ~/.daeasy/models)
  DAEASY_BLUR_WIFI     "0" 이면 Wi-Fi 단계 생략(기본 on)
"""
import os
import subprocess
from pathlib import Path

_DEFAULT_PY = r"C:\conda\envs\pro1\python.exe"


def preprocess_images(images_dir: Path) -> None:
    images_dir = Path(images_dir)
    if os.environ.get("DAEASY_BLUR", "1") == "0":
        print("[blur] DAEASY_BLUR=0 → 개인정보 블러 전처리 생략(원본이 그대로 사용됨)")
        return
    py = os.environ.get("DAEASY_BLUR_PYTHON", _DEFAULT_PY)
    models = os.environ.get("DAEASY_BLUR_MODELS", str(Path.home() / ".daeasy" / "models"))
    script = Path(__file__).resolve().parent / "blur" / "integrate_blur.py"

    if not Path(py).exists():
        raise RuntimeError(
            f"블러 실행 파이썬을 찾을 수 없습니다: {py}\n"
            f"DAEASY_BLUR_PYTHON 으로 cv2/onnxruntime/easyocr 설치된 파이썬을 지정하거나, "
            f"의도적으로 건너뛰려면 DAEASY_BLUR=0 을 설정하세요.")
    if not Path(models).exists():
        raise RuntimeError(f"블러 모델 경로가 없습니다: {models} (DAEASY_BLUR_MODELS 로 지정)")

    args = [py, str(script), "preprocess", str(images_dir), models]
    if os.environ.get("DAEASY_BLUR_WIFI", "1") == "0":
        args.append("nowifi")
    if os.environ.get("DAEASY_BLUR_SCREEN", "1") == "0":
        args.append("noscreen")  # 이번 건처럼 노트북 화면을 일부러 가리지 않을 때
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)
    if r.stdout:
        print(r.stdout.rstrip())
    if r.returncode != 0:
        raise RuntimeError(
            f"개인정보 블러 전처리 실패(코드 {r.returncode}). 블러 안 된 원본이 "
            f"다운스트림으로 가지 않도록 중단합니다.\n{(r.stderr or '')[-1500:]}")
