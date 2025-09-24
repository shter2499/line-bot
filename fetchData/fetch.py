"""
ฟังก์ชันนี้จะไม่ raise exception ออกไป แต่จะคืน dict รูปแบบมาตรฐาน:
  {"ok": True,  "status": <int>, "data": <object>, "raw_text": <str>}  เมื่อสำเร็จ
  {"ok": False, "status": <int|None>, "error": <str>}                 เมื่อผิดพลาด

หมายเหตุ: ปัจจุบันมีการปิด verify SSL (verify=False) *ไม่ปลอดภัย* ใช้เฉพาะ DEV.
แนะนำให้ปรับเป็น verify=True และใช้ certificate ที่ถูกต้องใน production.
"""

from typing import Any, Dict, Optional
from urllib import response
from requests import RequestException
import json
import requests
import mimetypes

Header_token = "979A97D6-362B-4E32-BB8A-ABB4E27043FE test"
DEFAULT_URL = "https://192.168.3.107:8080/api/v3/requests/"
DEFAULT_HEADERS = {"authtoken": Header_token}


def fetch(data: list[str]) -> Dict[str, Any]:
    inp_data = {"input_data": f"{data}"}

    try:
        resp = requests.post(
            DEFAULT_URL, headers=DEFAULT_HEADERS, data=inp_data, verify=False)
    except RequestException as exc:
        return {"ok": False, "status": None, "error": f"request_failed: {exc}"}
    status = resp.status_code
    text = json.loads(resp.text)

    if not (200 <= status < 300):
        return {"ok": False, "status": status, "error": f"http_{status}", "data": text}

    try:
        data_obj = resp.json()
    except ValueError:
        data_obj = None

    return {"ok": True, "status": status, "data": data_obj, "raw_text": text}


def uploadFile(img):
    url = "https://192.168.3.107:8080/api/v3/requests/upload"
    headers = {"authtoken": Header_token}

    fileType = mimetypes.guess_type(img)
    files = []
    fileObj = ('input_file', (img, open(img, 'rb'), fileType[0]))
    files.append(fileObj)

    response = requests.post(url, headers=headers, files=files, verify=False)

    if response.status_code == 201:
        return json.loads(response.text)
    else:
        return {"ok": False, "status": response.status_code, "error": response.text}


__all__ = ["fetch"]
