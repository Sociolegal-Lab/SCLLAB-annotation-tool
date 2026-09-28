#!/usr/bin/env bash
# OCR 校對工具啟動檔 (Linux / macOS)
# 第一次執行會在本資料夾建立 .venv 並安裝 Flask, 之後直接啟動。
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    PY=""
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
            PY="$c"; break
        fi
    done
    if [ -z "$PY" ]; then
        echo "找不到 Python 3.8 以上版本, 請先安裝: https://www.python.org/downloads/"
        read -r -p "按 Enter 結束" _
        exit 1
    fi
    echo "第一次執行: 建立環境並安裝 Flask ..."
    "$PY" -m venv .venv
    .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
fi

.venv/bin/python tool.py "$@"
