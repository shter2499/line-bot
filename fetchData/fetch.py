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
# import mysql.connector  # ปิดการใช้งาน MySQL
import datetime
import pytz
import os
import uuid
    
try:
    import redis
except Exception:
    redis = None


def _strtobool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


REQUESTS_API_URL = os.getenv("REQUESTS_API_URL")
REQUESTS_API_TOKEN = os.getenv("REQUESTS_API_TOKEN")
REQUESTS_UPLOAD_URL = os.getenv("REQUESTS_UPLOAD_URL")
REQUESTS_VERIFY_SSL = _strtobool(os.getenv("REQUESTS_VERIFY_SSL"), default=False)

DEFAULT_HEADERS = {"authtoken": REQUESTS_API_TOKEN}
GLOBAL_PAUSE_REDIS_KEY = os.getenv("GLOBAL_PAUSE_REDIS_KEY", "bot:global:paused")
GLOBAL_PAUSE_SECONDS = int(os.getenv("BOT_GLOBAL_PAUSE_SECONDS", str(24 * 60 * 60)))
THAI_TZ = pytz.timezone("Asia/Bangkok")

def fetch(data: list[str]) -> Dict[str, Any]:
    print("[INFO] Sending data to Requests API...")
    inp_data = {"input_data": f"{data}"}

    try:
        resp = requests.post(
            REQUESTS_API_URL, headers=DEFAULT_HEADERS, data=inp_data, verify=False)
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

    response = requests.post(url, headers=headers, files=files, verify=False)
    print(f"[INFO] Received response with status code {response.status_code}")
    print(f"[INFO] Received response {response.text}")
    if response.status_code == 201:
        return json.loads(response.text)
    else:
        return {"ok": False, "status": response.status_code, "error": response.text}


def fetch_store(storeID: str, host: str = "localhost", port: int = 3306, user: str = "root", password: str = "", database: str = "store_name"):
    # ฟังก์ชันนี้ต้องใช้ MySQL - ปิดการใช้งานชั่วคราว
    print(f"[WARN] fetch_store() is disabled - MySQL not available")
    return []
    
    # db_config = {
    #     "host": os.getenv("MYSQL_HOST", host),
    #     "port": int(os.getenv("MYSQL_PORT", port)),
    #     "user": os.getenv("MYSQL_USER", user),
    #     "password": os.getenv("MYSQL_PASSWORD", password),
    #     "database": os.getenv("MYSQL_DATABASE", database),
    # }

    # mydb = None
    # cursor = None
    # try:
    #     safe_cfg = {k: (v if k != "password" else "***") for k, v in db_config.items()}
    #     print(f"[DB] Connecting to MySQL at {safe_cfg}")
    #     mydb = mysql.connector.connect(**db_config)
    #     cursor = mydb.cursor(dictionary=True)
    #     cursor.execute(
    #         f""" select site_name, standard, company_name from stores where site_name like '%{storeID}%' """)
    #     result = cursor.fetchall()
    #     return result

    # except mysql.connector.Error as e:
    #     print(f"[ERROR] MySQL error: {e}")
    #     return []
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if mydb is not None and mydb.is_connected():
    #             mydb.close()
    #     except Exception:
    #         pass


def search_duplicate(storeID: str):
    try:
        # เรียกใช้ฟังก์ชั่นเพื่อหาค่า epoch
        start_date = datetime.date.today().strftime('%Y-%m-%d')
        start_epoch, end_epoch = get_epoch(start_date)
        dup_url = ""
        dup_token = ""

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
        request = requests.get(url, headers=headers, params=params, verify=False)
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


# def _get_bot_status(user_id: str) -> int:
#     """ตรวจสอบ bot_status จาก DB line_service โดยตรง (1=ON, 0=OFF)
#     default คืน 1 ถ้าไม่พบ customer หรือเกิด error เพื่อความปลอดภัย"""
#     db_config = {
#         'host': os.getenv('MYSQL_HOST', 'host.docker.internal'),
#         'port': int(os.getenv('MYSQL_PORT', '3306')),
#         'user': os.getenv('MYSQL_USER', 'root'),
#         'password': os.getenv('MYSQL_PASSWORD', ''),
#         'database': os.getenv('MYSQL_DATABASE_LINE', 'line_service'),
#         'charset': 'utf8mb4',
#         'connection_timeout': 5,
#     }
#     conn = None
#     cursor = None
#     try:
#         conn = mysql.connector.connect(**db_config)
#         cursor = conn.cursor()
#         cursor.execute(
#             'SELECT bot_status FROM customers WHERE id = %s LIMIT 1',
#             (user_id,)
#         )
#         row = cursor.fetchone()
#         if row is None:
#             return 1  # ลูกค้าใหม่ยังไม่มีในระบบ → เปิดบอทเป็น default
#         status = row[0]
#         result = 1 if status is None else int(status)
#         # print(f"[bot_status] {user_id} = {result}")
#         return result
#     except Exception as e:
#         print(f"[ERROR] _get_bot_status failed: {e}")
#         return 1  # fail-safe: เปิดบอทเป็น default
#     finally:
#         try:
#             if cursor is not None:
#                 cursor.close()
#         except Exception:
#             pass
#         try:
#             if conn is not None and conn.is_connected():
#                 conn.close()
#         except Exception:
#             pass


def _get_redis_client():
    """สร้าง Redis client ตาม env; คืน None ถ้าใช้งาน Redis ไม่ได้"""
    if redis is None:
        print("[WARN] redis package not available; using DB fallback only")
        return None

    redis_url = os.getenv("REDIS_URL")
    try:
        if redis_url:
            return redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
                health_check_interval=30,
                retry_on_timeout=True,
            )

        return redis.Redis(
            host=os.getenv("REDIS_HOST", "host.docker.internal"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD", "") or None,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
        )
    except Exception as e:
        print(f"[WARN] Redis init failed: {e}")
        return None


def _get_active_global_pause_from_db() -> tuple[bool, int, Any]:
    """
    คืนค่า tuple: (is_paused, remaining_seconds, end_date)
    โดยอ่านจากตาราง bot_status เฉพาะ end_date ของช่วง pause ที่ยัง active
    แล้วคำนวณ is_paused และ remaining_seconds ในโค้ด
    
    ฟังก์ชันนี้ต้องใช้ MySQL - ปิดการใช้งานชั่วคราว
    """
    print(f"[WARN] _get_active_global_pause_from_db() is disabled - MySQL not available")
    return False, 0, None
    
    # conn = None
    # cursor = None
    # try:
    #     conn = mysql.connector.connect(**_get_line_service_db_config())
    #     cursor = conn.cursor()
    #     cursor.execute("SET time_zone = '+07:00'")
    #     cursor.execute(
    #         """
    #         SELECT end_date
    #         FROM bot_status
    #         WHERE status = 0
    #           AND start_date <= NOW()
    #           AND end_date > NOW()
    #         ORDER BY start_date DESC
    #         LIMIT 1
    #         """
    #     )
    #     row = cursor.fetchone()
    #     if not row:
    #         return False, 0, None

    #     end_date = row[0]
    #     thai_now_naive = datetime.datetime.now(THAI_TZ).replace(tzinfo=None)
    #     now = datetime.datetime.now(end_date.tzinfo) if getattr(end_date, "tzinfo", None) else thai_now_naive
    #     remaining = int((end_date - now).total_seconds())
    #     if remaining <= 0:
    #         return False, 0, end_date
    #     return True, remaining, end_date
    # except Exception as e:
    #     print(f"[ERROR] _get_active_global_pause_from_db failed: {e}")
    #     return False, 0, None
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if conn is not None and conn.is_connected():
    #             conn.close()
    #     except Exception:
    #         pass


def set_global_pause_24h(issued_by: str = "") -> Dict[str, Any]:
    """ตั้งสถานะ pause แบบ global เป็นเวลา 24 ชั่วโมง (ใช้ Redis เท่านั้น)"""
    thai_now = datetime.datetime.now(THAI_TZ)
    end_at = thai_now + datetime.timedelta(seconds=GLOBAL_PAUSE_SECONDS)
    pause_id = f"B{thai_now.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"

    # MySQL part - disabled
    # conn = None
    # cursor = None
    # try:
    #     conn = mysql.connector.connect(**_get_line_service_db_config())
    #     cursor = conn.cursor()
    #     cursor.execute("SET time_zone = '+07:00'")
    #     cursor.execute(
    #         """
    #         INSERT INTO bot_status (id, status, start_date, end_date)
    #         VALUES (%s, %s, NOW(), DATE_ADD(NOW(), INTERVAL %s SECOND))
    #         """,
    #         (pause_id, 0, GLOBAL_PAUSE_SECONDS)
    #     )
    #     conn.commit()
    # except Exception as e:
    #     print(f"[ERROR] set_global_pause_24h DB failed: {e}")
    #     return {"ok": False, "message": "db_error", "error": str(e)}
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if conn is not None and conn.is_connected():
    #             conn.close()
    #     except Exception:
    #         pass

    redis_ok = False
    redis_error = None
    client = _get_redis_client()
    if client is not None:
        try:
            client.set(GLOBAL_PAUSE_REDIS_KEY, str(int(end_at.timestamp())), ex=GLOBAL_PAUSE_SECONDS)
            redis_ok = True
        except Exception as e:
            redis_error = str(e)
            print(f"[WARN] set_global_pause_24h Redis failed: {e}")
            return {"ok": False, "message": "redis_error", "error": redis_error}
    else:
        return {"ok": False, "message": "redis_unavailable"}

    return {
        "ok": True,
        "paused": True,
        "pause_id": pause_id,
        "end_at": end_at.strftime("%Y-%m-%d %H:%M:%S"),
        "redis_ok": redis_ok,
        "redis_error": redis_error,
        "issued_by": issued_by,
    }


def force_global_start_now(issued_by: str = "") -> Dict[str, Any]:
    """ยกเลิก global pause ทันที (ลบ Redis key เท่านั้น)"""
    # MySQL part - disabled
    # conn = None
    # cursor = None
    # updated_rows = 0
    # try:
    #     conn = mysql.connector.connect(**_get_line_service_db_config())
    #     cursor = conn.cursor()
    #     cursor.execute("SET time_zone = '+07:00'")
    #     cursor.execute(
    #         """
    #         UPDATE bot_status
    #         SET end_date = NOW()
    #         WHERE status = 0
    #           AND start_date <= NOW()
    #           AND end_date > NOW()
    #         ORDER BY start_date DESC
    #         LIMIT 1
    #         """
    #     )
    #     updated_rows = cursor.rowcount or 0
    #     conn.commit()
    # except Exception as e:
    #     print(f"[ERROR] force_global_start_now DB failed: {e}")
    #     return {"ok": False, "message": "db_error", "error": str(e)}
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if conn is not None and conn.is_connected():
    #             conn.close()
    #     except Exception:
    #         pass

    redis_ok = False
    redis_error = None
    client = _get_redis_client()
    if client is not None:
        try:
            client.delete(GLOBAL_PAUSE_REDIS_KEY)
            redis_ok = True
        except Exception as e:
            redis_error = str(e)
            print(f"[WARN] force_global_start_now Redis delete failed: {e}")
            return {"ok": False, "message": "redis_error", "error": redis_error}
    else:
        return {"ok": False, "message": "redis_unavailable"}

    return {
        "ok": True,
        "paused": False,
        "updated_rows": 0,  # N/A when MySQL is disabled
        "redis_ok": redis_ok,
        "redis_error": redis_error,
        "issued_by": issued_by,
    }


def is_global_paused_hybrid() -> tuple[bool, Dict[str, Any]]:
    """
    เช็ก global pause จาก Redis เท่านั้น (ไม่มี DB fallback)
    """
    client = _get_redis_client()
    if client is not None:
        try:
            value = client.get(GLOBAL_PAUSE_REDIS_KEY)
            if value:
                ttl = client.ttl(GLOBAL_PAUSE_REDIS_KEY)
                return True, {
                    "source": "redis",
                    "ttl_seconds": int(ttl) if ttl is not None else -1,
                    "end_epoch": value,
                }
        except Exception as e:
            print(f"[WARN] is_global_paused_hybrid Redis read failed: {e}")

    # ไม่มี DB fallback - ถ้า Redis ไม่พร้อมถือว่าไม่ pause
    return False, {"source": "redis", "ttl_seconds": 0}
    
    # DB fallback - disabled
    # paused, remaining, end_date = _get_active_global_pause_from_db()
    # if not paused:
    #     return False, {"source": "db", "ttl_seconds": 0}

    # if client is not None and remaining > 0:
    #     try:
    #         client.set(GLOBAL_PAUSE_REDIS_KEY, str(int(end_date.timestamp())), ex=remaining)
    #         print(f"[INFO] Redis key repopulated from DB fallback (ttl={remaining}s)")
    #     except Exception as e:
    #         print(f"[WARN] Redis repopulate failed: {e}")

    # return True, {
    #     "source": "db",
    #     "ttl_seconds": remaining,
    #     "end_at": end_date.isoformat(sep=" ") if end_date else None,
    # }


def get_effective_bot_status(user_id: str) -> int:
    """คืนสถานะเปิด/ปิดบอทที่รวม per-customer + global pause แล้ว"""
    # customer_status = _get_bot_status(user_id)
    # if customer_status != 1:
    #     return 0

    paused, _meta = is_global_paused_hybrid()
    return 0 if paused else 1


__all__ = [
    "fetch",
    "uploadFile",
    "fetch_store",
    "search_duplicate",
    "get_epoch",
    # "_get_bot_status",
    "set_global_pause_24h",
    "force_global_start_now",
    "is_global_paused_hybrid",
    "get_effective_bot_status",
    "check_duplicate_ticket",
    "record_ticket_open",
]


def _get_line_service_db_config() -> dict:
    """คืน config สำหรับ DB line_service (ปิดการใช้งาน)"""
    print(f"[WARN] _get_line_service_db_config() is disabled - MySQL not available")
    return {}
    # return {
    #     "host": os.getenv("MYSQL_HOST", "localhost"),
    #     "port": int(os.getenv("MYSQL_PORT", 3306)),
    #     "user": os.getenv("MYSQL_USER", "root"),
    #     "password": os.getenv("MYSQL_PASSWORD", ""),
    #     "database": os.getenv("MYSQL_DATABASE_LINE", "line_service"),
    # }


def check_duplicate_ticket(branch: str) -> dict:
    """
    ตรวจสอบว่าสาขานี้เคยเปิด Ticket ในวันนี้แล้วหรือไม่
    ฟังก์ชันนี้ต้องใช้ MySQL - ปิดการใช้งานชั่วคราว
    
    Returns: {"found": bool, "ticket_id": str | None, "count": int}
    """
    print(f"[WARN] check_duplicate_ticket() is disabled - MySQL not available")
    return {"found": False, "ticket_id": None, "count": 0}
    
    # if not branch or not branch.strip():
    #     return {"found": False, "ticket_id": None, "count": 0}

    # mydb = None
    # cursor = None
    # try:
    #     mydb = mysql.connector.connect(**_get_line_service_db_config())
    #     cursor = mydb.cursor(dictionary=True)
    #     cursor.execute("""
    #         SELECT ticket_id, COALESCE(count, 0) AS count
    #         FROM tickets
    #         WHERE branch LIKE %s
    #           AND DATE(created_date) = DATE(NOW())
    #         ORDER BY created_date DESC
    #         LIMIT 1
    #     """, (f"%{branch.strip()}%",))
    #     print(f"[DB] Checking for duplicate ticket for branch '{branch.strip()}'...")
    #     row = cursor.fetchone()
    #     if row:
    #         current_count = int(row.get("count") or 0)
    #         new_count = current_count + 1
    #         cursor.execute("""
    #             UPDATE tickets
    #             SET count = %s
    #             WHERE ticket_id = %s
    #         """, (new_count, row["ticket_id"]))
    #         mydb.commit()
    #         print(f"[DB] Duplicate ticket found for branch '{branch}': {row['ticket_id']} (count={new_count})")
    #         return {"found": True, "ticket_id": row["ticket_id"], "count": new_count}
    #     return {"found": False, "ticket_id": None, "count": 0}
    # except mysql.connector.Error as e:
    #     print(f"[ERROR] check_duplicate_ticket failed: {e}")
    #     return {"found": False, "ticket_id": None, "count": 0}
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if mydb is not None and mydb.is_connected():
    #             mydb.close()
    #     except Exception:
    #         pass


def record_ticket_open(branch: str, ticket_id: str, customer_id: str = '') -> None:
    """
    บันทึกการเปิด Ticket ลงตาราง tickets ใน line_service เพื่อตรวจสอบ Ticket ซ้ำ
    ฟังก์ชันนี้ต้องใช้ MySQL - ปิดการใช้งานชั่วคราว
    """
    print(f"[WARN] record_ticket_open() is disabled - MySQL not available")
    return
    
    # if not branch or not ticket_id:
    #     return

    # mydb = None
    # cursor = None
    # try:
    #     mydb = mysql.connector.connect(**_get_line_service_db_config())
    #     cursor = mydb.cursor()
    #     cursor.execute("""
    #         INSERT INTO tickets (ticket_id, branch, customer_id, created_date)
    #         VALUES (%s, %s, %s, NOW())
    #     """, (str(ticket_id), branch.strip(), customer_id or ''))
    #     mydb.commit()
    #     print(f"[DB] Recorded ticket: ticket_id={ticket_id}, branch='{branch}', customer_id='{customer_id}'")
    # except mysql.connector.Error as e:
    #     print(f"[ERROR] record_ticket_open failed: {e}")
    # finally:
    #     try:
    #         if cursor is not None:
    #             cursor.close()
    #     except Exception:
    #         pass
    #     try:
    #         if mydb is not None and mydb.is_connected():
    #             mydb.close()
    #     except Exception:
    #         pass


def send_helpdesk_alert(branch: str, ticket_id: str, duplicate_count: int) -> bool:
    """
    ส่งแจ้งเตือน LINE push ไปหา Helpdesk OA เมื่อมีการแจ้งซ้ำผิดปกติ
    ต้องตั้ง HELPDESK_LINE_CHANNEL_ACCESS_TOKEN และ TARGET_ID ไว้ใน env
    """
    channel_access_token = os.getenv("HELPDESK_LINE_CHANNEL_ACCESS_TOKEN")
    target_id = os.getenv("HELPDESK_TARGET_ID")
    print(f"[DEBUG] token_prefix={channel_access_token[:10]}... target_id='{target_id}' len={len(target_id)}")

    if not channel_access_token or not target_id:
        print("[WARN] send_helpdesk_alert skipped: missing HELPDESK_LINE_CHANNEL_ACCESS_TOKEN or HELPDESK_TARGET_ID in env")
        return False

    message_text = (
        "⚠️ แจ้งเตือนสาขาแจ้งงานซ้ำผิดปกติ\n"
        f"สาขา: {branch}\n"
        f"เลขงาน: {ticket_id}\n"
        f"จำนวนครั้งวันนี้: {duplicate_count}\n"
        "กรุณาตรวจสอบสาเหตุและประสานสาขา"
    )

    try:
        response = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={
                "Authorization": f"Bearer {channel_access_token}",
                "Content-Type": "application/json",
            },
            json={
                "to": target_id,
                "messages": [{"type": "text", "text": message_text}],
            },
            timeout=10,
        )
        if 200 <= response.status_code < 300:
            print(f"[HELPDESK] Alert sent for branch '{branch}' (count={duplicate_count})")
            return True

        print(f"[ERROR] send_helpdesk_alert failed: {response.status_code} {response.text}")
        return False
    except Exception as e:
        print(f"[ERROR] send_helpdesk_alert exception: {e}")
        return False