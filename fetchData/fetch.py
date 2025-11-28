"""
หมายเหตุ:
- ปัจจุบันมีการปิด verify SSL (verify=False) ซึ่งไม่ปลอดภัย ใช้เฉพาะ DEV เท่านั้น
- ย้ายค่าคอนฟิกที่เปลี่ยนตามสภาพแวดล้อม (URL, Token, DB host/port) ไปที่ Environment Variables
    เพื่อให้ทำงานได้ทั้งบนเครื่องจริงและใน Docker โดยไม่แก้โค้ด
"""

from typing import Any, Dict
from requests import RequestException
import json
import requests
import mimetypes
import mysql.connector
import datetime
import pytz
import os


def _strtobool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


REQUESTS_API_URL = os.getenv("REQUESTS_API_URL")
REQUESTS_API_TOKEN = os.getenv("REQUESTS_API_TOKEN")
REQUESTS_UPLOAD_URL = os.getenv("REQUESTS_UPLOAD_URL")
REQUESTS_VERIFY_SSL = _strtobool(os.getenv("REQUESTS_VERIFY_SSL"), default=False)

DEFAULT_HEADERS = {"authtoken": REQUESTS_API_TOKEN}

def fetch(data: list[str]) -> Dict[str, Any]:
    print("[INFO] Sending data to Requests API...")
    inp_data = {"input_data": f"{data}"}

    try:
        resp = requests.post(
            REQUESTS_API_URL, headers=DEFAULT_HEADERS, data=inp_data, verify=REQUESTS_VERIFY_SSL)
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
    url = REQUESTS_UPLOAD_URL
    headers = {"authtoken": REQUESTS_API_TOKEN}

    fileType = mimetypes.guess_type(img)
    files = []
    fileObj = ('input_file', (img, open(img, 'rb'), fileType[0]))
    files.append(fileObj)

    response = requests.post(url, headers=headers,
                             files=files, verify=REQUESTS_VERIFY_SSL)
    print(f"[INFO] Received response with status code {response.status_code}")
    print(f"[INFO] Received response {response.text}")
    if response.status_code == 201:
        return json.loads(response.text)
    else:
        return {"ok": False, "status": response.status_code, "error": response.text}


def fetch_store(storeID: str, host: str = "localhost", port: int = 3306, user: str = "root", password: str = "", database: str = "store_name"):
    db_config = {
        "host": os.getenv("MYSQL_HOST", host),
        "port": int(os.getenv("MYSQL_PORT", port)),
        "user": os.getenv("MYSQL_USER", user),
        "password": os.getenv("MYSQL_PASSWORD", password),
        "database": os.getenv("MYSQL_DATABASE", database),
    }

    mydb = None
    cursor = None
    try:
        safe_cfg = {k: (v if k != "password" else "***") for k, v in db_config.items()}
        print(f"[DB] Connecting to MySQL at {safe_cfg}")
        mydb = mysql.connector.connect(**db_config)
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(
            f""" select site_name, standard, company_name from stores where site_name like '%{storeID}%' """)
        result = cursor.fetchall()
        return result

    except mysql.connector.Error as e:
        print(f"[ERROR] MySQL error: {e}")
        # Return empty list to avoid None-index errors upstream
        return []
    finally:
        try:
            if cursor is not None:
                cursor.close()
        except Exception:
            pass
        try:
            if mydb is not None and mydb.is_connected():
                mydb.close()
        except Exception:
            pass


def search_duplicate(storeID: str):
    try:
        # เรียกใช้ฟังก์ชั่นเพื่อหาค่า epoch
        start_date = datetime.date.today().strftime('%Y-%m-%d')
        start_epoch, end_epoch = get_epoch(start_date)
        dup_url = "http://192.168.1.12:443/api/v3/requests"
        dup_token = "9F24A1C1-98A9-4C48-AEA3-7666D5DBC02B"

        # แสดงข้อมูลวันที่ที่จะค้นหา
        thailand_tz = pytz.timezone('Asia/Bangkok')
        start_dt = datetime.datetime.fromtimestamp(
            start_epoch / 1000, thailand_tz)
        end_dt = datetime.datetime.fromtimestamp(end_epoch / 1000, thailand_tz)

        # print(f"ค้นหาข้อมูลช่วงวันที่: {start_dt.strftime('%Y-%m-%d')} ถึง {end_dt.strftime('%Y-%m-%d')}")
        dup_api_url = os.getenv("DUP_API_URL", dup_url)
        dup_api_token = os.getenv("DUP_API_TOKEN", dup_token) # EXP 08/11/2025 (dmy)   
        dup_verify_ssl = _strtobool(os.getenv("DUP_VERIFY_SSL"), default=False)
        url = dup_api_url
        headers = {"authtoken": dup_api_token}
        input_data = f'''{{
            "list_info": {{
                "row_count": 1000,
                "start_index": 1,
                "sort_field": "id",
                "sort_order": "desc",
                "get_total_count": true,
                "search_criteria": [            
                    {{
                        "field": "requester.name",
                        "condition": "is",
                        "value": "{storeID}"
                    }},
                    {{
                        "field": "created_time",
                        "condition": "greater than",
                        "value": "{start_epoch}",
                        "logical_operator": "AND"
                    }},
                    {{
                        "field": "subject",
                        "condition": "contains",
                        "value": "POS#1 Promptpay",
                        "logical_operator": "AND"
                    }},
                ]
            }}
        }}'''

        # ถ้าจะให้แสดงวันที่ตรงกับ timezone ของไทยต้องเลือกห้าโมงเย็นของเมื่อวาน ในเว็บ epochconverter หรือค่า epoch -61200000 ms ถึงจะได้ GMT+7

        params = {'input_data': input_data}
        request = requests.get(url, headers=headers,
                               params=params, verify=dup_verify_ssl)
        res = request.json()
        print("=" * 50)
        print(f"[REQUEST] {res}")
        print("=" * 50)
        return res
    except RequestException as exc:
        print(" ⚠️ " * 20)
        print(f"[ERROR] request_failed: {exc}")
        print(" ⚠️ " * 20)
        return {"ok": False, "status": None, "error": f"request_failed: {exc}"}
    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR] search_duplicate failed: {e}")
        print(" ⚠️ " * 20)
        return {"ok": False, "status": None, "error": f"unexpected: {e}"}


def get_epoch(start_date=None, end_date=None):
    # สร้าง timezone ไทย
    thailand_tz = pytz.timezone('Asia/Bangkok')

    # ถ้าไม่ระบุวันที่เริ่มต้น ใช้วันที่ปัจจุบัน
    if start_date is None:
        start_day = datetime.datetime.now(thailand_tz)
    else:
        # แปลงสตริงวันที่เป็น datetime object
        try:
            start_day = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            start_day = thailand_tz.localize(start_day)
        except ValueError:
            print(
                f"รูปแบบวันที่เริ่มต้นไม่ถูกต้อง: {start_date}, ใช้รูปแบบ YYYY-MM-DD")
            start_day = datetime.datetime.now(thailand_tz)

    # ถ้าไม่ระบุวันที่สิ้นสุด ใช้วันที่เดียวกับวันเริ่มต้น
    if end_date is None:
        end_day = start_day
    else:
        # แปลงสตริงวันที่เป็น datetime object
        try:
            end_day = datetime.datetime.strptime(end_date, '%Y-%m-%d')
            end_day = thailand_tz.localize(end_day)
        except ValueError:
            print(
                f"รูปแบบวันที่สิ้นสุดไม่ถูกต้อง: {end_date}, ใช้รูปแบบ YYYY-MM-DD")
            end_day = start_day

    # ตั้งเวลาเริ่มต้น 00:00:00 และสิ้นสุด 23:59:59
    start_time = start_day.replace(hour=0, minute=0, second=0, microsecond=0)
    end_time = end_day.replace(hour=23, minute=59, second=59, microsecond=0)

    # แปลงเป็น epoch timestamp (ms)
    start_epoch = int(start_time.timestamp() * 1000)
    end_epoch = int(end_time.timestamp() * 1000)

    return start_epoch, end_epoch


__all__ = [
    "fetch",
    "uploadFile",
    "fetch_store",
    "search_duplicate",
    "get_epoch",
]
