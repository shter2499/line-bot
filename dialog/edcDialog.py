"""
State management now uses Redis via session.RedisSession instead of in-memory dict.
- Session TTL is enforced by Redis; no manual _expire needed. ✅
- Timers are managed in-process per instance (stored outside Redis) as they are not JSON-serializable.
"""
from __future__ import annotations

from fetchData.fetch import fetch, uploadFile, fetch_store, search_duplicate
from dialog.aiDialog import send_message, process_message, process_part
import predict_classifier
import predict_cr_classifier
import predict_image_edc
from session import RedisSession

import os
import re
import time
import threading
import json
from PIL import Image
from typing import Dict, Optional, Callable


SESSION_TIMEOUT_SEC = 600
_reply_cb: Optional[Callable[[str, str], None]] = None
_redis: Optional[RedisSession] = None
_timers: Dict[str, threading.Timer] = {}


def _get_redis() -> RedisSession:
    global _redis
    if _redis is None:
        # Use environment-driven configuration from session.RedisSession
        # This respects REDIS_URL / REDIS_HOST / REDIS_PORT inside Docker
        _redis = RedisSession()
    return _redis


def _default_state(uid: str, reply_token: str) -> Dict:
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
        "reply_token": reply_token
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


def _start(uid: str,reply_token: str):
    st = _default_state(uid,reply_token)
    _save_state(uid, st)
    return st


def _clear(uid: str):
    # cancel local timer if exists
    t = _timers.pop(uid, None)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
    _delete_state(uid)


def _auto_reply(user_id: str):
    print("[_auto_reply] Triggered for user_id....")
    state = _load_state(user_id)
    if not state:
        return

    # Ensure part3 flag and reset step without overwriting other fields
    state = _patch_state(user_id, {"step": 0, "data": {"part3": True}})
    if state.get("image_paths")[0] not in state["history"] and not state.get("context_confirm"):
        history = state.get("history", [])
        image_path = state.get("image_paths")[0]
        history.append(image_path)
        state = _patch_state(user_id, {"history": history})
        _reply_cb(state.get("reply_token", ""),
                  "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
        return

    # res = send_message("ห้ามขอรูปซ้ำอีก", state)
    if state.get("img_confirm") and state["data"].get("part1") and state["data"].get("part2"):
        data = f"ส่วนที่หนึ่ง: {state['data'].get('text1')}\nส่วนที่สอง: {state['data'].get('text2')}\nส่วนที่สาม: มีรูปภาพประกอบแล้ว "
        _summary(state, data)
    else:
        _reply_cb(state.get("reply_token", ""), res)
        # _reply_cb(state.get("reply_token", ""), "")


def _schedule_auto_submit(user_id: str, delay_sec: float = 5.0):
    old = _timers.get(user_id)
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t = threading.Timer(delay_sec, _auto_reply, args=(user_id,))
    t.daemon = True
    _timers[user_id] = t
    t.start()


def _summary(state: Dict, txt) -> str:
    print("=" * 50)
    print(f"[_summary] [txt] {txt}")
    print("=" * 50)
    image_paths = state.get('image_paths', [])
    user_id = state.get("uid")
    state = _load_state(user_id)
    result = find_branch(txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0])
    branch = result["site_name"] if result else None
    standard = result["standard"] if result else None
    company = result["company_name"] if result else None
    header = parse_header(txt.split("ส่วนที่สอง:")[1].split('\n')[0])

    try:
        detail = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[1]
        user = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[2]
        phone = txt.split("ส่วนที่หนึ่ง:")[1].split(',')[3].split("\n")[0]
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
            "description": f"ชื่อผู้แจ้ง  : {user}<br />เบอร์ติดต่อ : {phone}<br />สถานที่/บริษัท/สาขา พบปัญหา : {branch if branch is not None else txt.split('ส่วนที่หนึ่ง:')[1].split(',')[0]}<br />ปัญหาที่พบ/คำร้องขอ : {detail}<br />SN : N/A<br />Model : Not Specified",
            "requester": {
                "name": branch if branch is not None else txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0]
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
            "udf_fields": {
                "udf_sline_902": phone,
                "udf_sline_62": "สาขา",
                "udf_pick_1801": company,
                "udf_pick_8705": "EDC",
                "udf_pick_9601": "BBL",
                "udf_sline_611": "N/A",
                "udf_sline_1507": f"{'POS#1 ชำระผ่านบัตรเครดิตแล้วบิลไม่ตัด' if cr_test.get('prediction') == 'cr' else f'POS#1 Promptpay ชำระสำเร็จแล้วบิลไม่ตัดที่ POS({header})'}",
                "udf_mline_4203": f"ชื่อผู้แจ้ง  : {user}\nเบอร์ติดต่อ : {phone}\nสถานที่/บริษัท/สาขา พบปัญหา : {branch if branch is not None else txt.split('ส่วนที่หนึ่ง:')[1].split(',')[0]}\nปัญหาที่พบ/คำร้องขอ : {detail}\nSN : N/A\nModel : Not Specified",
                "udf_date_68": {
                    "display_value": "2025/11/28 07:35",
                    "value": "1764229800000"
                },
                "udf_pick_2115": {
                    "name": "Service Desk",
                    "id": "2082"
                },
                "udf_pick_2116": {
                    "name": "test Items",
                    "id": "2032"
                },
                "udf_pick_2117": {
                    "name": "Watcharit Chomklin",
                    "id": "2033"
                }
            },
            "attachments": attachment_list
        }
    }

    # print("=" * 50)
    # print(f"[PAYLOAD] {json.dumps(payload, ensure_ascii=False)}")
    # print("=" * 50)

    print("[INFO] Sending ticket creation request...")
    resp = fetch(payload)
    # resp = {"ok": False}

    if resp.get("ok"):
        for img_path in image_paths:
            if img_path and os.path.isfile(img_path):
                try:
                    os.remove(img_path)
                except OSError as e:
                    print(f"[WARN] remove image failed: {e}")
        try:
            ticket_id = resp['data']['request']['id']
            res_txt = f"""Ticket {ticket_id} โดยมีรายละเอียดดังนี้\nชื่อสาขาหรือรหัสสาขา: {branch if branch is not None else txt.split("ส่วนที่หนึ่ง:")[1].split(',')[0]}\nปัญหาที่พบ: {detail}\nชื่อ: {user}\nเบอร์โทรติดต่อ: {phone}"""
            _reply_cb(state.get("reply_token", ""), res_txt)
            _clear(user_id)
        except Exception as e:
            ticket_id = "-"
            _reply_cb(state.get("reply_token", ""),
                      "ตอนนี้ระบบมีปัญหาอยู่ รอสักครู่นะครับ")
            return f"[ERROR]: {e}"
    return "ตอนนี้ระบบบันทึกข้อมูลไม่ได้ กรุณารอสักครู่ครับ"


def _handle_edc_message(user_id: str, lower: str) -> Optional[str]:
    """ตัว test จะมีไว้แยกว่าข้อความที่รับเข้ามาอยู่ใน part ไหนบ้าง หลังจากนั้นข้อมูลของ part นั้นจะถูกส่งต่อไปที่
    send_message เพื่อให้ AI จัดเรียงข้อมูลใหม่ก่อนจะบันทึกลง state อีกครั้ง
    """
    state = _load_state(user_id) or _default_state(user_id)

    # ตอนนี้รองรับเฉพาะกรณีเริ่ม flow ใหม่ (step == 0)
    if state.get("step", 0) != 0:
        # อยู่ระหว่าง flow อื่นอยู่ ให้ไม่ทำอะไรเพิ่มเติม
        return None

        if not state:
            state = _start(user_id, reply_token)
        if reply_token:
            state["reply_token"] = reply_token

    part = json.loads(process_message(lower, state))
    format_data = json.loads(process_part(lower, state))
    print("=" * 50)
    print(f"[handle edc message part] {part}")
    print(f"[handle edc message test] {format_data}")
    print(f"[state data] {state['data']}")
    print("=" * 50)
    res = ''
    if part.get("part1"):
        print("[INFO] Processing part 1...")
        branch = format_data.get("part1").split("รหัสสาขาและชื่อสาขา:")[1].split("\n")[0] 
        issue = format_data.get("part1").split("ปัญหาที่พบ:")[1].split("\n")[0] 
        name = format_data.get("part1").split("ชื่อ:")[1].split("\n")[0] 
        phone = format_data.get("part1").split("เบอร์ติดต่อ:")[1] 
        print(f"[CHECK PART1] branch:{ branch}, issue:{ issue}, name:{ name}, phone:{ phone}")

        if branch == '' or issue == '' or name == '' or phone == '':
            _patch_state(user_id, {"step": 0})
            return "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:"
        else:
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "text1": f"{branch}, {issue}, {name}, {phone}",
                },
            })

        if state["data"]["part2"] == True and state["data"]["part3"] == True:
            print("[INFO] Proceeding to summary...")
            data = f"ส่วนที่หนึ่ง: {state['data'].get('text1')}\nส่วนที่สอง: {state['data'].get('text2')}\nส่วนที่สาม: มีรูปภาพประกอบแล้ว "
            _summary(state, data)
            return None
        elif state["data"]["part2"] == False or state["data"]["part3"] == False:
            res = send_message(f"{format_data.get('part1')}", state)

    if part.get("part2"):
        print("[INFO] Processing part 2...")
        frezez = format_data.get("part2").split("Ans:")[1].split("\n")[0]
        restart = format_data.get("part2").split("Ans:")[2].split("\n")[0]
        slip = format_data.get("part2").split("Ans:")[3]
        print(f"[CHECK PART2] frezez:{ frezez}, restart:{ restart}, slip:{ slip}")
        print("=" * 50)
        print(f"[CHECK STATE] {state}")
        print("=" * 50)
        if frezez == '' or restart == '' or slip == '':
            _patch_state(user_id, {"step": 0})
            return "รบกวนขอข้อมูลตามนี้หน่อยครับ\nเครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"
        else:
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part2": True,
                    "text2": f"""{frezez}, {restart}, {slip}""",
                },
            })

        if state["data"]["part1"] == True and state["data"]["part3"] == True:
            print("[INFO] Proceeding to summary...")
            data = f"ส่วนที่หนึ่ง: {state['data'].get('text1')}\nส่วนที่สอง: {state['data'].get('text2')}\nส่วนที่สาม: มีรูปภาพประกอบแล้ว "
            _summary(state, data)
            return None
        elif state["data"]["part1"] == False or state["data"]["part3"] == False:
            res = send_message(f"{format_data.get('part2')}", state)
        # res = send_message(f"{format_data.get('part2')}", state)

    print("=" * 50)
    print(f"[INFO] AI Response: {res}")
    print("=" * 50)

    # ถ้า AI ตอบมาครบทุกส่วนแล้วให้ไปสรุปเลย ไม่ต้องส่งข้อความกลับไปอีก
    if ("ส่วนที่สอง:" in res) and ("ส่วนที่สาม:" in res):
        print("[INFO] Proceeding to summary...")
        _summary(state, res)
        return None

    # ยังไม่ครบ ให้ส่งข้อความนี้กลับไปถามข้อมูลเพิ่ม แล้ว reset step
    state["step"] = 0
    _save_state(user_id, state)
    # return 
    return res


def process_step_message(user_id: str, text: str, reply_token: Optional[str] = None) -> str:
    print("START PROCESS STEP MESSAGE")
    state = _load_state(user_id)
    predic = predict_classifier.classify(text)
    print("=" * 50)
    print(f"[PREDICTION] {predic}")
    print("=" * 50)

    if not state:
        state = _start(user_id,reply_token)
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
        return "ยกเลิกเซสชันแล้ว"

    prediction = predic.get("prediction")
    reply_text: Optional[str] = None

    if prediction == "edc":
        reply_text = _handle_edc_message(user_id, state, lower)
    elif prediction == "other":
        reply_text = ""

    # ส่งข้อความกลับ (ถ้ามี callback และกำหนด reply_text มา)
    if reply_token and _reply_cb and reply_text is not None:
        _reply_cb(reply_token, reply_text)

    return None


def process_image_message(user_id: str, image_path: str, reply_token: Optional[str] = None) -> Optional[str]:
    state = _load_state(user_id)
    predic_img = predict_image_edc.classify_image(image_path)
    print("=" * 50)
    print(f"[PREDICTION IMAGE] {predic_img}")
    print("=" * 50)

    if predic_img.get("prediction") == "not_edc":
        return None
    if not state:
        print(f"[WARN] image from user without session: {user_id}")
        state = _start(user_id,reply_token)

    image_paths = state.get("image_paths", [])
    image_paths.append(image_path)

    updates = {
        "img_confirm": True,
        "image_paths": image_paths,
        "data": {"part3": True},
    }
    if reply_token:
        updates["reply_token"] = reply_token

    _save_state(user_id, state)
    _schedule_auto_submit(user_id, delay_sec=5.0)
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

    except Exception as e:
        print(" ⚠️ " * 20)
        print(f"[ERROR] find_branch error: {e}")
        print(" ⚠️ " * 20)
        return None


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
    return f"EDC {edc_freeze}, Slip EDC {edc_slip}"


__all__ = ["process_step_message",
           "process_image_message", "set_reply_callback"]
