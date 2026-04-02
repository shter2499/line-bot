"""
State management now uses Redis via session.RedisSession instead of in-memory dict.
- Session TTL is enforced by Redis; no manual _expire needed. ✅
- Timers are managed in-process per instance (stored outside Redis) as they are not JSON-serializable.
"""
from __future__ import annotations
import datetime

from fetchData.fetch import fetch, uploadFile, fetch_store, search_duplicate
from dialog.aiDialog import requester, process_message, process_part
import predict_classifier
import predict_cr_classifier
import predict_image_edc
from session import RedisSession

import os
import re
import time
import threading
import json
import requests
from typing import Dict, Optional, Callable


SESSION_TIMEOUT_SEC = 600
_reply_cb: Optional[Callable[[str, str], None]] = None
_redis: Optional[RedisSession] = None
_timers: Dict[str, threading.Timer] = {}
_timer_lock = threading.Lock()  # Thread-safe timer management


def _get_redis() -> RedisSession:
    global _redis
    if _redis is None:
        # Use environment-driven configuration from session.RedisSession
        # This respects REDIS_URL / REDIS_HOST / REDIS_PORT inside Docker
        _redis = RedisSession()
    return _redis


def _default_state(uid: str) -> Dict:
    return {
        "step": 0,
        "answers": [],
        "edc_answers": [],
        "updated": time.time(),
        "uid": uid,
        "image_paths": [],
        "history": [],
        "context_confirm": False,
        "img_confirm": False,
        "edc_confirm": False,
        "reply_token": "",
        "processing_summary": False,
        "ticket_created": False,
        "ticket_id": "",
        "ticket_reply_token": "",
        "ignore_group":[""],
        "data": {
            "part1": False,
            "text1": {"branch": "", "issue": "", "name": "", "phone": ""},
            "tmp1": [],
            "reply1": False,
            "part2": False,
            "text2": {"freeze": "", "restart": "", "slip": ""},
            "tmp2": [],
            "reply2": False,
            "part3": False,
            "reply3": False,
        }
    }


def _load_state(uid: str) -> Optional[Dict]:
    try:
        data = _get_redis().get(uid)
        return data
    except Exception as e:
        print(f"[ERROR] load state failed for {uid}: {e}")
        return None


def _save_state(uid: str, state: Dict) -> None:
    try:
        state["updated"] = time.time()
        _get_redis().save(uid, state)
    except Exception as e:
        print(f"[ERROR] save state failed for {uid}: {e}")


def _patch_state(uid: str, updates: Dict) -> Dict:
    """Update only specific keys in the latest state stored in Redis.

    - Loads the newest state (or default if missing).
    - Applies top-level updates from `updates`.
    - If `updates` contains a `data` dict, merges it into `state["data"]`.
    - Persists the merged state via _save_state and returns it.
    """
    # Load the latest state snapshot
    state = _load_state(uid) or _default_state(uid)

    # Separate nested data updates (do not mutate the original dict)
    data_updates = updates.get("data") if isinstance(updates.get("data"), dict) else None

    # Apply top-level keys except "data"
    for key, value in updates.items():
        if key == "data":
            continue
        state[key] = value

    # Deep-merge into state["data"] if provided
    if data_updates is not None:
        if "data" not in state or not isinstance(state["data"], dict):
            state["data"] = {}
        for key, value in data_updates.items():
            state["data"][key] = value

    _save_state(uid, state)
    return state


def _delete_state(uid: str) -> None:
    try:
        _get_redis().delete(uid)
    except Exception as e:
        print(f"[ERROR] delete state failed for {uid}: {e}")


def set_reply_callback(cb: Callable[[str, str], None]) -> None:
    """Register a callback used to reply later using a stored reply_token.

    cb will be called as cb(reply_token, text).
    """
    global _reply_cb
    _reply_cb = cb


def _send_bot_response(customer_id: str, reply_token: str, text: str, retry_count: int = 0) -> None:
    """Send bot response to external API running on host machine."""
    max_retries = 2
    try:
        # Use environment variable or default to host.docker.internal (for Docker)
        bot_api_url = os.getenv("BOT_RESPONSE_API_URL", "http://host.docker.internal:3001/api/bot_response")
        
        payload = {
            "customer_id": customer_id,
            "reply_token": reply_token,
            "text": text
        }
        response = requests.post(bot_api_url, json=payload, timeout=15)
        response.raise_for_status()
        print(f"[_send_bot_response] Success: {response.status_code}")
    except requests.exceptions.Timeout:
        if retry_count < max_retries:
            print(f"[WARNING] Timeout occurred, retrying... ({retry_count + 1}/{max_retries})")
            time.sleep(1)
            return _send_bot_response(customer_id, reply_token, text, retry_count + 1)
        else:
            print(f"[ERROR] Max retries reached, giving up on sending response")
    except requests.exceptions.ConnectionError:
        print(f"[WARNING] Bot response API unavailable at {bot_api_url}. Continuing without sending response.")
    except Exception as e:
        print(f"[ERROR] _send_bot_response failed: {e}")


def _start(uid: str):
    st = _default_state(uid)
    _save_state(uid, st)
    return st


def _safe_cancel_timer(uid: str):
    """Thread-safe timer cancellation"""
    with _timer_lock:
        old = _timers.pop(uid, None)
        if old:
            try:
                old.cancel()
                print(f"[DEBUG] Timer safely cancelled for {uid}")
            except Exception as e:
                print(f"[WARN] Failed to cancel timer for {uid}: {e}")

def _clear(uid: str):
    # cancel local timer if exists
    _safe_cancel_timer(uid)
    _delete_state(uid)

def _get_field_value(new_value: str, existing_value: str) -> str:
    """Helper function to determine which field value to use.
    
    Returns new_value if existing_value is empty/whitespace-only,
    otherwise returns existing_value to preserve user data.
    """
    return new_value if not existing_value.strip() else existing_value


def _build_text1_data(branch: str, issue: str, name: str, phone: str, current_text1: dict) -> dict:
    """Helper function to build text1 data with proper field preservation."""
    return {
        "branch": _get_field_value(branch, current_text1.get("branch", "")),
        "issue": _get_field_value(issue, current_text1.get("issue", "")),
        "name": _get_field_value(name, current_text1.get("name", "")),
        "phone": _get_field_value(phone, current_text1.get("phone", ""))
    }


def _build_text2_data(freeze: str, restart: str, slip: str, current_text2: dict) -> dict:
    """Helper function to build text2 data with proper field preservation."""
    return {
        "freeze": _get_field_value(freeze, current_text2.get("freeze", "")),
        "restart": _get_field_value(restart, current_text2.get("restart", "")),
        "slip": _get_field_value(slip, current_text2.get("slip", ""))
    }


def _submit_parts(user_id: str, parts: str):
    print("=" * 50)
    print(f"[_submit_parts] Triggered for user_id {user_id} and parts {parts}")
    state = _load_state(user_id)
    if not state or not isinstance(state, dict):
        print(f"[ERROR] Invalid state for user {user_id}: {state}")
        return
    
    # เช็คว่า ticket ถูกสร้างไปแล้วหรือไม่
    if state.get("ticket_created", False):
        print(f"[WARNING] Ticket already created for {user_id}, skipping _submit_parts")
        return
        
    # ตรวจสอบว่ากำลังประมวลผล summary อยู่ไหม
    if state.get("processing_summary", False):
        print(f"[WARNING] Summary already in progress for {user_id}, aborting _submit_parts")
        return
        
    data = state.get("data")
    for i in state["ignore_group"]:
        if i in user_id:
            print(f"[_submit_parts] Ignored group {i}...")
            _clear(user_id)
            return
    # print(f"[CHECK STATE BEFORE SUBMIT] {state['data']['text1']}")
    
    if parts == "part1":
        print("[_submit_parts] Processing part 1...")
        join_tmp = ",".join(data.get("tmp1"))
        format_data = process_part(join_tmp, state)
        print(f"[CHECK FORMAT DATA PART1] {format_data}")
        try:
            parsed_data = json.loads(format_data)
            part1_content = parsed_data.get("part1", "")
            
            # ใช้ regex เพื่อ parse ข้อมูลแต่ละฟิลด์อย่างแม่นยำ
            branch = ""
            issue = ""
            name = ""
            phone = ""
            
            # Parse รหัสสาขา
            branch_match = re.search(r'รหัสสาขาและชื่อสาขา:\s*([^\n\r]*)', part1_content)
            if branch_match:
                branch = branch_match.group(1).strip()
            
            # Parse ปัญหาที่พบ
            issue_match = re.search(r'ปัญหาที่พบ:\s*([^\n\r]*)', part1_content)
            if issue_match:
                issue = issue_match.group(1).strip()
            
            # Parse ชื่อ
            name_match = re.search(r'ชื่อ:\s*([^\n\r]*)', part1_content)
            if name_match:
                name = name_match.group(1).strip()
            
            # Parse เบอร์ติดต่อ
            phone_match = re.search(r'เบอร์ติดต่อ:\s*([^\n\r"]*)', part1_content)
            if phone_match:
                phone = phone_match.group(1).strip()
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"[ERROR] Failed to parse part1 format_data: {e}")
            branch = issue = name = phone = ""
        # print(f"[CHECK PART1] branch({branch}) == '':{ branch == ''},\nissue({issue}) == '':{ issue == ''},\nname({name}) == '':{ name == ''},\nphone({phone}) == '':{ phone == ''},\nreply1:{ data['reply1'] }")

        # ตรวจสอบว่าข้อมูลไม่ครบ
        has_incomplete_data = (not branch.strip() or not issue.strip() or not name.strip() or not phone.strip())
        
        if has_incomplete_data and data["reply1"] == False:
            # ครั้งแรกที่ข้อมูลไม่ครบ - ให้ AI สร้างคำถาม (ไม่ clear tmp1 เพื่อรักษาข้อมูลเดิม)
            text1_data = _build_text1_data(branch, issue, name, phone, data['text1'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "reply1": True,
                    "text1": text1_data,
                },
            })
            _send_bot_response(user_id, state.get("reply_token", ""), json.loads(format_data).get("part1"))
            # Clear tmp1 หลังประมวลผลเสร็จ
            _patch_state(user_id, {"data": {"tmp1": []}})
            return
        elif has_incomplete_data and data["reply1"] == True:
            # ครั้งที่สองที่ข้อมูลไม่ครบ - ขอข้อมูลที่ขาดโดยตรง (ไม่ clear tmp1 เพื่อรักษาข้อมูลเดิม)
            text1_data = _build_text1_data(branch, issue, name, phone, data['text1'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "reply1": True,
                    "text1": text1_data,
                },
            })
            # หาฟิลด์ที่ยังว่าง
            req_data = []
            for key in state["data"]['text1'].keys():
                if not state["data"]['text1'][key].strip():
                    req_data.append(key)
                
            request = requester(','.join(req_data))
            _send_bot_response(user_id, state.get("reply_token", ""), request)
            # Clear tmp1 หลังประมวลผลเสร็จ
            _patch_state(user_id, {"data": {"tmp1": []}})
            return
        else:
            # ข้อมูล part1 ครบแล้ว - บันทึกและดำเนินการต่อ
            text1_data = _build_text1_data(branch, issue, name, phone, data['text1'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "tmp1": [],
                    "text1": text1_data,
                },
            })
            # หากมีข้อมูล part2 รอ ให้ประมวลผลทันที
            if state["data"]["tmp2"]:
                _submit_parts(user_id, "part2")
                return
            
        # หาก part1 ครบแล้วและยังไม่มี part2 ให้ถาม part2
        if (branch.strip() and issue.strip() and name.strip() and phone.strip() and 
            state["data"]["part2"] == False and state["data"]["tmp2"] == []):
            print("[INFO] Asking for part 2 data from part 1...")
            state = _patch_state(user_id, {"data": {"reply2": True}})
            _send_bot_response(user_id, state.get("reply_token", ""), "เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:")
            return
        
    if parts == "part2":
        print("[_submit_parts] Processing part 2...")
        join_tmp = ",".join(data.get("tmp2"))
        format_data = process_part(join_tmp, state)
        try:
            parsed_data = json.loads(format_data)
            part2_content = parsed_data.get("part2", "")
            ans_parts = part2_content.split("Ans:")
            freeze = ans_parts[1].split("\\n")[0] if len(ans_parts) > 1 else ""
            restart = ans_parts[2].split("\\n")[0] if len(ans_parts) > 2 else ""
            slip = ans_parts[3].split('"')[0] if len(ans_parts) > 3 else ""
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"[ERROR] Failed to parse part2 format_data: {e}")
            freeze = restart = slip = ""
        # print(f"[CHECK PART2] freeze:{ freeze}, restart:{ restart}, slip:{ slip}")
        # ตรวจสอบว่าข้อมูลไม่ครบ
        has_incomplete_part2 = (not freeze.strip() or not restart.strip() or not slip.strip())
        
        if has_incomplete_part2 and data["reply2"] == False:
            # ครั้งแรกที่ข้อมูลไม่ครบ - ให้ AI สร้างคำถาม (ไม่ clear tmp2 เพื่อรักษาข้อมูลเดิม)
            text2_data = _build_text2_data(freeze, restart, slip, data['text2'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part2": True,
                    "reply2": True,
                    "text2": text2_data,
                },
            })
            _send_bot_response(user_id, state.get("reply_token", ""), json.loads(format_data).get("part2"))
            # Clear tmp2 หลังประมวลผลเสร็จ
            _patch_state(user_id, {"data": {"tmp2": []}})
            return
        elif has_incomplete_part2 and data["reply2"] == True:
            # ครั้งที่สองที่ข้อมูลไม่ครบ - ขอข้อมูลที่ขาดโดยตรง (ไม่ clear tmp2 เพื่อรักษาข้อมูลเดิม)
            text2_data = _build_text2_data(freeze, restart, slip, data['text2'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part2": True,
                    "text2": text2_data,
                },
            })
            # หาฟิลด์ที่ยังว่าง
            req_data = []
            for key in state["data"]['text2'].keys():
                if not state["data"]['text2'][key].strip():
                    req_data.append(key)
                
            request = requester(','.join(req_data))
            _send_bot_response(user_id, state.get("reply_token", ""), request)
            # Clear tmp2 หลังประมวลผลเสร็จ
            _patch_state(user_id, {"data": {"tmp2": []}})
            return
        else:
            # ข้อมูล part2 ครบแล้ว - บันทึกและดำเนินการต่อ
            text2_data = _build_text2_data(freeze, restart, slip, data['text2'])
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part2": True,
                    "tmp2": [],
                    "text2": text2_data,
                },
            })
            # หากมีข้อมูล part1 รอ ให้ประมวลผลทันที
            if state["data"]["tmp1"]:
                _submit_parts(user_id, "part1")
                return
                
        # หาก part2 ครบแล้วและยังไม่มี part3 ให้ถามรูปภาพ
        if (freeze.strip() and restart.strip() and slip.strip() and 
            state["data"]["part3"] == False and state["image_paths"] == []):
            print("[INFO] Asking for part 3 data from part 2...")
            print(f"[CHECK STATE BEFORE PART3] {state}")
            _send_bot_response(user_id, state.get("reply_token", ""), "รบกวนขอรูปภาพประกอบด้วยครับ")
            return
            
        # หาก part2 ครบแต่ยังไม่มี part1 ให้ถาม part1
        if (freeze.strip() and restart.strip() and slip.strip() and 
            state["data"]["part1"] == False and state["data"]["reply1"] == False and 
            state["data"]["tmp1"] == []):
            print("[INFO] Asking for part 1 data from part 2...")
            state = _patch_state(user_id, {"data": {"reply1": True}})
            _send_bot_response(user_id, state.get("reply_token", ""), "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
            return
        
    if parts == "part3":
        print("[_submit_parts] Processing part 3...")
        print(f"[CHECK STATE BEFORE PART3] {state['data']}")
        state = _patch_state(user_id, {
            "step": 0,
            "data": {
                "part3": True,
            },
        })
        # เช็ค reply flag ของแต่ละ part โดยตรง
        if not state["data"]["part1"] and state["data"]["tmp1"] == [] and not data.get("reply1", False):
            print("[INFO] Asking for part 1 data from part 3...")
            state = _patch_state(user_id, {"data": {"reply1": True}})
            _send_bot_response(user_id, state.get("reply_token", ""), "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
            return
        if not state["data"]["part2"] and state["data"]["tmp2"] == [] and not data.get("reply2", False):
            print("[INFO] Asking for part 2 data from part 3...")
            state = _patch_state(user_id, {"data": {"reply2": True}})
            _send_bot_response(user_id, state.get("reply_token", ""), "รบกวนขอข้อมูลตามนี้หน่อยครับ\nเครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:")
            return

    print(f"[CHECK STATE AFTER SUBMIT PARTS] {state['data']}")
    if state["data"]["part1"] == True and state["data"]["part2"] == True and state["data"]["part3"] == True:
        print("[INFO] All parts received, proceeding to final submission...")
        req_data = []
        # ตรวจสอบข้อมูล part1 ก่อนสร้าง ticket
        text1 = state["data"]["text1"]
        if (not text1["branch"].strip() or not text1["issue"].strip() or 
            not text1["name"].strip() or not text1["phone"].strip()):
            print("[INFO] Missing part 1 data, cannot proceed to summary.")
            for key in text1.keys():
                if not text1[key].strip():
                    req_data.append(key)
            request = requester(','.join(req_data))
            _send_bot_response(user_id, state.get("reply_token", ""), request)
            return
            
        # ตรวจสอบข้อมูล part2 ก่อนสร้าง ticket
        text2 = state["data"]["text2"]
        if (not text2["freeze"].strip() or not text2["restart"].strip() or 
            not text2["slip"].strip()):
            print("[INFO] Missing part 2 data, cannot proceed to summary.")
            for key in text2.keys():
                if not text2[key].strip():
                    req_data.append(key)
            request = requester(','.join(req_data))
            _send_bot_response(user_id, state.get("reply_token", ""), request)
            return
        print("[INFO] Proceeding to summary...")
        data = {
            "part1": state["data"].get("text1"),
            "part2": state["data"].get("text2"),
            "part3": "มีรูปภาพประกอบแล้ว",
        }
        _summary(user_id, data)
        return
    elif state["data"]["tmp1"]:
        _submit_parts(user_id, "part1")
    elif state["data"]["tmp2"]:
        _submit_parts(user_id, "part2")
    elif state["image_paths"] == []:
        _send_bot_response(user_id, state.get("reply_token", ""), "รบกวนขอรูปภาพประกอบด้วยครับ")
        return

def _schedule_auto_submit(user_id: str, delay_sec: float = 10.0):
    # เช็คว่า ticket ถูกสร้างไปแล้วหรือไม่
    state = _load_state(user_id)
    if state and state.get("ticket_created", False):
        print(f"[INFO] Ticket already created for {user_id}, skipping timer")
        return
    
    # Thread-safe timer management
    with _timer_lock:
        old = _timers.get(user_id)
        if old:
            try:
                old.cancel()
                print(f"[DEBUG] Cancelled old timer for {user_id}")
            except Exception as e:
                print(f"[WARN] Failed to cancel timer: {e}")
        
        t = threading.Timer(delay_sec, _submit_parts, args=(user_id, "part3"))
        t.daemon = True
        _timers[user_id] = t
        t.start()
        print(f"[DEBUG] Started new timer for {user_id}")


def _summary(user_id: str, txt: dict) -> str:
    thread_id = threading.get_ident()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DEBUG] _summary called - user:{user_id}, thread:{thread_id}, time:{timestamp}")
    state = _load_state(user_id)
    
    # ตรวจสอบว่ากำลังประมวลผล summary อยู่ไหม
    if state.get("processing_summary", False):
        print(f"[WARNING] _summary already in progress for {user_id}, skipping...")
        return None
    
    # เช็ค ticket ที่สร้างแล้ว
    if state.get("ticket_created", False):
        ticket_id = state.get("ticket_id", "")
        print(f"[WARNING] Ticket already created for {user_id}: {ticket_id}")
        _send_bot_response(user_id, state.get("reply_token", ""),f"เลขงานครับ {ticket_id}")
        return None
    
    # เช็ค reply_token ซ้ำ
    current_reply_token = state.get("reply_token", "")
    ticket_reply_token = state.get("ticket_reply_token", "")
    if ticket_reply_token and current_reply_token == ticket_reply_token:
        print(f"[WARNING] Duplicate reply_token detected for {user_id}: {current_reply_token}")
        return None
    
    print(f"[DEBUG] Setting processing_summary flag - user:{user_id}, thread:{thread_id}")
    # ตั้ง flag ป้องกันการเรียกซ้ำ แบบ atomic
    _patch_state(user_id, {
        "processing_summary": True,
        "ticket_reply_token": current_reply_token
    })
    
    try:
        image_paths = state.get('image_paths', [])
        part1 = txt["part1"]
        part2 = txt["part2"]
        part3 = txt["part3"]
        print("=" * 50)
        print(f"[_summary] [txt] {txt}")
        print(f"[state] {state}")
        # print(f"[branch] {branch}, [standard] {standard}, [company] {company}, [header] {header}")
        # print(f"[result] {result}")
        print("=" * 50)
        user_id = state.get("uid")
        result = find_branch(part1.get("branch", ""))
        branch = result["site_name"] if result else None
        standard = result["standard"] if result else None
        company = result["company_name"] if result else None
        
        # แก้ไขปัญหาเมื่อ find_branch หาข้อมูลสาขาไม่เจอ
        if branch is None:
            branch_data = part1.get('branch', '').strip()
            print(f"[DEBUG] find_branch not found, checking branch_data: {branch_data}")
            
            # ตรวจสอบว่าข้อมูล branch ไม่ใช่ข้อมูลปัญหา
            problem_keywords = ['ปัญหาที่พบ:', 'พร้อมเพย์', 'บิลไม่ตัด', 'ไม่ตัด', 'EDC', 'POS']
            if branch_data and not any(keyword in branch_data for keyword in problem_keywords):
                branch = branch_data
                print(f"[DEBUG] Using branch_data as fallback: {branch}")
            else:
                branch = "ไม่ระบุสาขา"
                print(f"[DEBUG] Branch data contains problem keywords or empty, using default: {branch}")
        else:
            print(f"[DEBUG] find_branch success: {branch}")
        th_tz = datetime.timezone(datetime.timedelta(hours=7))
        now_th = datetime.datetime.now(th_tz)
        display_time = now_th.strftime("%Y/%m/%d %H:%M")
        eporch_time = int(now_th.timestamp() * 1000)
        print(f"[CHECK DISPLAY TIME] {display_time}, eporch_time: {eporch_time}")
        header = parse_header(f"{part2.get('freeze', '')},{part2.get('restart', '')},{part2.get('slip', '')}")
        # dup = search_duplicate(branch)

        # if dup["response_status"][0]["status_code"] == 2000 and dup['list_info']['total_count'] > 0:
        #     _reply_cb(state.get("reply_token", ""),
        #               f"สาขาได้แจ้งงานมาแล้วครับ Ticket {dup['requests'][0]['id']}")
        #     _clear(user_id)
        #     return
        try:
            detail = part1.get("issue", "")
            user = part1.get("name", "")
            phone = part1.get("phone", "")
        except Exception as e:
            print(" ⚠️ " * 20)
            print(f"[ERROR] parsing answers failed: {e}")
            print(" ⚠️ " * 20)
            return "ระบบมีปัญหา กรุณารอสักครู่ครับ"

        # อัปโหลดรูปทุกรูปและเก็บ attachment IDs
        print("[INFO] Uploading attachments...")
        attachment_list = []
        for img_path in image_paths:
            if img_path and os.path.isfile(img_path):
                try:
                    file_result = uploadFile(img_path)
                    if file_result and file_result.get('attachment'):
                        attachment_list.append(
                            {"id": file_result['attachment']['id']})
                except Exception as e:
                    print(f"[WARN] upload failed for {img_path}: {e}")
        cr_test = predict_cr_classifier.classify(detail)

        payload = {
            "request": {
                "subject": f"{'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}",
                "description": f"ชื่อผู้แจ้ง : {user}<br />เบอร์ติดต่อ : {phone}<br />สถานที่/บริษัท/สาขา พบปัญหา : {branch}<br />ปัญหาที่พบ/คำร้องขอ : {'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}<br />SN : N/A<br />Model : Not Specified",
                "requester": {
                    "name": branch
                },
                "resolution": {
                    "content": "<div>เเนะนำสาขาทำ Memo เเจ้ง เเอเรีย<br /></div>"
                },
                "template": {
                    "id": "5101",
                    "name": "New Aloha System for Minor (DQ-BT-BS-CF)",
                    "is_service_template": 'false'
                },
                "site": {
                    "id": "302",
                    "name": "Dairy Queen - Standard A"  # ใส่แบบนี้ไปก่อนเพราะยังแยกไม่ได้
                },
                "item": {
                    "id": "4501",
                    "name": "EDC – Payment - ITMX"
                },
                "priority": {
                    "id": "6",
                    "name": "Severity 2"
                },
                "mode": {
                    "id": "4",
                    "name": "Chat"
                },
                "status": {
                    "id": "2",
                    "name": "Open",
                    "color": "#0066ff"
                },
                "group": {
                    "id": "463",
                    "name": "Service Desk",
                    "site": {
                            "id": 302
                    }
                },
                "category": {
                    "id": "603",
                    "name": "SOFTWARE"
                },
                "subcategory": {
                    "id": "3310",
                    "name": "EDC Payment"
                },
                "technician": {
                    "id": "5402",
                    "email_id": "Helpdesk@p5-management.com",
                    "name": "Service Desk",
                    "phone": None,
                    "mobile": None
                },
                "udf_fields": {
                    "udf_sline_902": phone,
                    "udf_sline_62": "สาขา",
                    "udf_pick_1801": "Dairy Queen",
                    "udf_pick_8705": "EDC",
                    "udf_pick_9601": "BBL",
                    "udf_sline_611": "N/A",
                    "udf_sline_1507": f"{'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}",
                    "udf_mline_4203": f"ชื่อผู้แจ้ง  : {user}\nเบอร์ติดต่อ : {phone}\nสถานที่/บริษัท/สาขา พบปัญหา : {branch}\nปัญหาที่พบ/คำร้องขอ : {detail}\nSN : N/A\nModel : Not Specified",
                    "udf_date_68": {
                        "display_value": display_time,
                        "value": eporch_time
                    },
                    "udf_date_8101": {
                        "display_value": display_time,
                        "value": eporch_time
                    },
                    "udf_pick_64": "กฤตภาส ศิริโสภณพิพัฒน์",
                    "udf_pick_612": "NO",
                    "udf_pick_4802": "P5",
                    "udf_pick_9302": "Software"
                },
                "attachments": attachment_list
            }
        }

        print("=" * 50)
        print(f"[PAYLOAD] {json.dumps(payload, ensure_ascii=False)}")
        print("=" * 50)

        print(f"[INFO {user_id}] Sending ticket creation request...")
        resp = fetch(payload)
        # resp = {"ok": False}

        if resp.get("ok"):
            for img_path in image_paths:
                if img_path and os.path.isfile(img_path):
                    try:
                        os.remove(img_path)
                    except OSError as e:
                        print(f"[WARN {user_id}] remove image failed: {e}")
            try:
                ticket_id = resp['data']['request']['id']
                
                # บันทึกข้อมูล ticket ที่สร้างสำเร็จ
                _patch_state(user_id, {
                    "ticket_created": True,
                    "ticket_id": ticket_id,
                    "processing_summary": False
                })
                
                # ยกเลิก timer ที่อาจยังทำงานอยู่ด้วย thread-safe method
                _safe_cancel_timer(user_id)
                print(f"[DEBUG {user_id}] Timer cancelled after ticket creation")
                
                print("=" * 50)
                print(f"[INFO {user_id}]: Ticket {ticket_id} created successfully")
                print("=" * 50)
                
                res_txt = f"เลขงานครับ {ticket_id}"
                _send_bot_response(user_id, current_reply_token, res_txt)
                
                # อย่า _clear() ทันที เพื่อให้ ticket info อยู่ใน state
                
            except Exception as e:
                # ถ้าเกิดข้อผิดพลาด ให้ reset flag แต่ไม่ต้อง reset ticket info
                _patch_state(user_id, {"processing_summary": False})
                _send_bot_response(user_id, current_reply_token, "รอเลขงานสักครู่นะครับ")
                print(f"[ERROR {user_id}] parsing ticket ID failed: {e}")
                return f"[ERROR]: {e}"
        else:
            # ถ้า fetch ไม่สำเร็จ ให้ reset flag
            _patch_state(user_id, {"processing_summary": False})
            _send_bot_response(user_id, current_reply_token, "ระบบขัดข้อง กรุณาลองใหม่อีกครั้ง")
            
    except Exception as e:
        # ถ้าเกิดข้อผิดพลาดในส่วนอื่น ให้ reset flag
        _patch_state(user_id, {"processing_summary": False})
        print(f"[ERROR {user_id}] _summary failed: {e}")
        raise e


def _handle_edc_message(user_id: str, lower: str, reply_token: str) -> Optional[str]:
    """ตัว test จะมีไว้แยกว่าข้อความที่รับเข้ามาอยู่ใน part ไหนบ้าง หลังจากนั้นข้อมูลของ part นั้นจะถูกส่งต่อไปที่
    send_message เพื่อให้ AI จัดเรียงข้อมูลใหม่ก่อนจะบันทึกลง state อีกครั้ง
    """
    state = _load_state(user_id)
    
    # เช็คว่า ticket ถูกสร้างไปแล้วหรือไม่
    if state and state.get("ticket_created", False):
        ticket_id = state.get("ticket_id", "")
        print(f"[INFO {user_id}] Ticket already exists: {ticket_id}")
        # ไม่ส่ง response ซ้ำ - ticket ถูกส่งไปแล้วใน _summary()
        return None

    history = state.get("history", [])
    history.append(lower)
    state = _patch_state(user_id, {
        "reply_token": reply_token,
        "history": history,
        "context_confirm": True,
    })

    part = json.loads(process_message(lower, state))
    
    if part.get("part1"):
        # เอาข้อมูลที่ลูกค้าพิมพ์มาเก็บเป็น list ชั่วคราว แล้วค่อย join เป็น string ส่งให้ AI แทน
        print(f"[INFO {user_id}] Processing part 1...")
        latest = _load_state(user_id)
        
        # เช็ค ticket ก่อนสร้าง timer ใหม่
        if latest and latest.get("ticket_created", False):
            print(f"[INFO {user_id}] Ticket already created, skipping part1 processing")
            return None
            
        data = latest.get("data")
        tmp = list(data.get("tmp1"))
        tmp.append(lower)
        state = _patch_state(user_id, {
            "data": {"tmp1": tmp}
        })
        print(f"[CHECK TMP1] {state['data'].get('tmp1')}")
        # ตั้ง timer สำหรับ part1 ด้วย thread-safe method
        with _timer_lock:
            old = _timers.get(user_id)
            if old:
                try:
                    old.cancel()
                except Exception:
                    pass
            t = threading.Timer(10.0, _submit_parts, args=(user_id, "part1"))
            t.daemon = True
            _timers[user_id] = t
            t.start()
            print(f"[DEBUG] Part1 timer set for {user_id}")
        
    if part.get("part2"):
        print(f"[INFO {user_id}] Processing part 2...")
        latest = _load_state(user_id)
        
        # เช็ค ticket ก่อนสร้าง timer ใหม่
        if latest and latest.get("ticket_created", False):
            print(f"[INFO {user_id}] Ticket already created, skipping part2 processing")
            return None
            
        data = latest.get("data")
        tmp = list(data.get("tmp2"))
        tmp.append(lower)
        state = _patch_state(user_id, {
            "data": {"tmp2": tmp}
        })
        print(f"[CHECK TMP2] {state['data'].get('tmp2')}")
        # ตั้ง timer สำหรับ part2 ด้วย thread-safe method
        with _timer_lock:
            old = _timers.get(user_id)
            if old:
                try:
                    old.cancel()
                except Exception:
                    pass
            t = threading.Timer(10.0, _submit_parts, args=(user_id, "part2"))
            t.daemon = True
            _timers[user_id] = t
            t.start()
            print(f"[DEBUG] Part2 timer set for {user_id}")


def process_step_message(user_id: str, text: str, reply_token: Optional[str] = None) -> str:
    print("START PROCESS STEP MESSAGE")
    state = _load_state(user_id)
    raw_text = (text or "").strip()
    normalized_text = _normalize_branch_in_text(user_id, raw_text)
    print(f"[PATTERN] normalized_text: {normalized_text}")
    predic = predict_classifier.classify(raw_text)
    print("=" * 50)
    print(f"[PREDICTION] {predic}")
    print("=" * 50)

    if not state:
        state = _start(user_id)
    if reply_token:
        state["reply_token"] = reply_token
        if not state:
            state = _start(user_id, reply_token)
        if reply_token:
            state["reply_token"] = reply_token

    msg = (text or "").strip()
    lower = msg.lower()

    # คำสั่งยกเลิก flow
    if lower == "ยกเลิก":
        _clear(user_id)
        _send_bot_response(user_id, reply_token, "ยกเลิกเซสชันแล้ว")
        # return "ยกเลิกเซสชันแล้ว"

    prediction = predic.get("prediction")
    reply_text: Optional[str] = None

    if prediction == "edc":
        # กรณีเป็น EDC ให้ไปจัดการในฟังก์ชันเฉพาะ
        print(f"[INFO {user_id}] Handling EDC message..." )
        reply_text = _handle_edc_message(user_id, lower, reply_token)
    elif prediction == "other":
        # ไม่ใช่ EDC - หยุดการทำงานโดยไม่ส่งอะไรกลับ
        print(f"[INFO {user_id}] Non-EDC message received, sending empty response." )
        # _send_bot_response(user_id, reply_token, " ")
        return None



def process_image_message(user_id: str, image_path: str, reply_token: Optional[str] = None) -> Optional[str]:
    state = _load_state(user_id)
    predic_img = predict_image_edc.classify_image(image_path)
    print("=" * 50)
    print(f"[PREDICTION IMAGE {user_id}] {predic_img}")
    print("=" * 50)

    if predic_img.get("prediction") == "not_edc":
        return None
    if not state:
        state = _start(user_id)

    image_paths = state.get("image_paths", [])
    image_paths.append(image_path)
    updates = {
        "img_confirm": True,
        "image_paths": image_paths,
        "data": {"part3": True},
        "reply_token": reply_token
    }
    state = _patch_state(user_id, updates)
    _schedule_auto_submit(user_id, delay_sec=10.0)
    
    return None


def find_branch(storeID: str):
    try:
        pattern = r"\d{6}|\d{5}|\d{4}"
        matched = re.search(pattern, storeID)
        print(f"[PATTERN]: {pattern}, Matched: {matched}")

        if matched:
            ID = matched.group(0)
            result = fetch_store(ID)
            return result[0]
        else:
            return None

    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR] find_branch error: {e}")
        print(" ⚠️ " * 20)
        return None


def _normalize_branch_in_text(user_id: str, text: str) -> str:
    """
    ใช้ find_branch หา site_name แล้วแทนลงในข้อความ

    เคสที่รองรับ:
    - ข้อความหลายบรรทัดที่มี "รหัสสาขาและชื่อสาขา:" -> แทนทั้งบรรทัดนั้นด้วย site_name
    - ข้อความที่มีแต่รหัสสาขา เช่น "1350" -> คืนเป็น site_name ตรง ๆ
    """
    result = find_branch(text)
    if not result:
        return text

    site_name = result.get("site_name")
    if not site_name:
        return text

    lines = text.splitlines()
    _patch_state(user_id, {"data": {"text1": {"branch": site_name,"issue": "", "name": "", "phone": ""}}})
    for i, line in enumerate(lines):
        if "รหัสสาขาและชื่อสาขา:" in line:
            # แทนทั้งบรรทัดให้เป็นชื่อสาขาตาม find_branch
            lines[i] = f"รหัสสาขาและชื่อสาขา:{site_name}"
            return "\n".join(lines)

    # ถ้าไม่มีบรรทัด "รหัสสาขาและชื่อสาขา:" แสดงว่าอาจส่งมาแค่รหัส เช่น "1350"
    return site_name


def parse_header(text: str):
    edc_freeze = text.split(",")[0]
    edc_slip = text.split(",")[2]
    if ("ไม่" in edc_freeze):
        edc_freeze = "ไม่ค้าง"
    elif ("ใช่" in edc_freeze):
        edc_freeze = "ค้าง"

    if ("ไม่" in edc_slip):
        edc_slip = "ไม่ออก"
    elif ("ใช่" in edc_slip):
        edc_slip = "ออก"
    return f"EDC {edc_freeze},TIME,APP, Slip EDC {edc_slip}"


__all__ = ["process_step_message",
           "process_image_message", "set_reply_callback"]
