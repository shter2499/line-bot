"""
หมายเหตุ: ปัจจุบันมีการปิด verify SSL (verify=False) *ไม่ปลอดภัย* ใช้เฉพาะ DEV.
แนะนำให้ปรับเป็น verify=True และใช้ certificate ที่ถูกต้องใน production.
"""

from typing import Any, Dict
from requests import RequestException
import json
import requests
import mimetypes
import mysql.connector
import datetime
import pytz

Header_token = "F91D9A0A-A60B-4A6C-94E9-27BA1CB96DD0" #EXPIRED 10/10/2025
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


def fetch_store(storeID: str):
    db_config = {
        "host": "localhost",
        "user": "root",
        "password": "ranma2499",
        "database": "store_name"
    }

    try:
        mydb = mysql.connector.connect(**db_config)
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(
            f""" select site_name, standard from stores where site_name like '%{storeID}%' """)
        result = cursor.fetchall()
        return result

    except mysql.connector.Error as e:
        print(f"[ERROR] MySQL error: {e}")
    finally:
        cursor.close()
        mydb.close()


def search_duplicate(storeID: str):
    try:
        # เรียกใช้ฟังก์ชั่นเพื่อหาค่า epoch
        start_date = datetime.date.today().strftime('%Y-%m-%d')
        start_epoch, end_epoch = get_epoch(start_date)

        # แสดงข้อมูลวันที่ที่จะค้นหา
        thailand_tz = pytz.timezone('Asia/Bangkok')
        start_dt = datetime.datetime.fromtimestamp(
            start_epoch / 1000, thailand_tz)
        end_dt = datetime.datetime.fromtimestamp(end_epoch / 1000, thailand_tz)

        # print(f"ค้นหาข้อมูลช่วงวันที่: {start_dt.strftime('%Y-%m-%d')} ถึง {end_dt.strftime('%Y-%m-%d')}")

        url = "http://192.168.1.12:443/api/v3/requests"
        headers = {"authtoken": "9568C77F-4978-4920-ABCD-7700E99A3B9F"}
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
        request = requests.get(url, headers=headers,params=params, verify=False)
        res = request.json()

        return res
    except RequestException as exc:
        print(" ⚠️ " * 20)
        print(f"[ERROR] request_failed: {exc}")
        print(" ⚠️ " * 20)
        return {"ok": False, "status": None, "error": f"request_failed: {exc}"}


def get_epoch(start_date=None, end_date=None):
    """
    คำนวณค่า epoch timestamp สำหรับเขตเวลาไทย

    Args:
        start_date (str, optional): วันที่เริ่มต้นในรูปแบบ 'YYYY-MM-DD' เช่น '2025-08-05'
        end_date (str, optional): วันที่สิ้นสุดในรูปแบบ 'YYYY-MM-DD' เช่น '2025-08-06'
        ถ้าไม่ระบุจะใช้วันที่ปัจจุบัน (start=end=today)
    Returns:
        tuple: (start_epoch, end_epoch) ค่า epoch timestamp ในหน่วย milliseconds
    """
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


__all__ = ["fetch", "fetch_store"]
