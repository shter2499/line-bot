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


def _start(uid: str):
    st = _default_state(uid)
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
        print("[_auto_reply] No state found, exiting...")
        return

    # Ensure part3 flag and reset step without overwriting other fields
    state = _patch_state(user_id, {"data": {"part3": True}})
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
        _summary(user_id, data)
    else:
        if state["data"]["part1"] == False:
            reply = "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:"
            _reply_cb(state.get("reply_token", ""), reply)
            return
        
        if state["data"]["part2"] == False:
            reply = "รบกวนขอข้อมูลตามนี้หน่อยครับ\nเครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:"
            _reply_cb(state.get("reply_token", ""), reply)
            return
    

def _submit_parts(user_id: str, parts: str):
    print("=" * 50)
    print(f"[_submit_parts] Triggered for user_id {user_id} and parts {parts}")
    state = _load_state(user_id)
    data = state.get("data")
    
    if parts == "part1":
        print("[_submit_parts] Processing part 1...")
        join_tmp = ",".join(data.get("tmp1"))
        format_data = process_part(join_tmp, state)
        branch = format_data.split("รหัสสาขาและชื่อสาขา:")[1].split("\\n")[0]
        issue = format_data.split("ปัญหาที่พบ:")[1].split("\\n")[0]
        name = format_data.split("ชื่อ:")[1].split("\\n")[0]
        phone = format_data.split("เบอร์ติดต่อ:")[1].split('"}')[0]
        print(f"[CHECK PART1] branch: {branch}, \nissue: {issue}, \nname: {name}, \nphone: {phone}")

        if (branch == '' or issue == '' or name == '' or phone == '') and data["reply1"] == False:
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "reply1": True,
                    "tmp1": [],
                    "text1": {"branch": branch if data['text1']['branch'] == "" else data['text1']['branch'], 
                                "issue": issue if data['text1']['branch'] == "" else data['text1']['issue'], 
                                "name": name if data['text1']['branch'] == "" else data['text1']['name'], 
                                "phone": phone if data['text1']['branch'] == "" else data['text1']['phone']},
                },
            })
            _reply_cb(state.get("reply_token", ""), json.loads(format_data).get("part1"))
        else:
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part1": True,
                    "tmp1": [],
                    "text1": {"branch": branch if data['text1']['branch'] == "" else data['text1']['branch'], 
                                "issue": issue if data['text1']['branch'] == "" else data['text1']['issue'], 
                                "name": name if data['text1']['branch'] == "" else data['text1']['name'], 
                                "phone": phone if data['text1']['branch'] == "" else data['text1']['phone']},
                },
            })
            print(f"[CHECK STATE AFTER PART1] {state}")
            
        if branch != '' and issue != '' and name != '' and phone != '' and state["data"]["part2"] == False:
            _reply_cb(state.get("reply_token", ""), "เครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:")
        
    if parts == "part2":
        print("[_submit_parts] Processing part 2...")
        join_tmp = ",".join(data.get("tmp2"))
        format_data = process_part(join_tmp, state)
        freeze = format_data.split("Ans:")[1].split("\\n")[0]
        restart = format_data.split("Ans:")[2].split("\\n")[0]
        slip = format_data.split("Ans:")[3].split('"}')[0]
        print(f"[CHECK PART2] freeze:{ freeze}, restart:{ restart}, slip:{ slip}")
        if (freeze == '' or restart == '' or slip == '') and data["reply2"] == False:
            _patch_state(user_id, {"step": 0, "data": {"reply2": True}})
            state = _patch_state(user_id, {
                "step": 0,
                "data": {
                    "part2": True,
                    "tmp2": [],
                    "text2": {"freeze": freeze if data["text2"]["freeze"] == "" else data["text2"]["freeze"], 
                              "restart": restart if data["text2"]["restart"] == "" else data["text2"]["restart"], 
                              "slip": slip if data["text2"]["slip"] == "" else data["text2"]["slip"]},
                },
            })
            _reply_cb(state.get("reply_token", ""), json.loads(format_data).get("part2"))
        else:
            state = _patch_state(user_id, {
                "step": 0,
                "tmp2": [],
                "data": {
                    "part2": True,
                    "tmp2": [],
                    "text2": {"freeze": freeze, "restart": restart, "slip": slip},
                },
            })
            if state["data"]["tmp1"]:
                _submit_parts(user_id, "part1")
                
        if freeze != '' and restart != '' and slip != '' and state["data"]["part3"] == False:
            _reply_cb(state.get("reply_token", ""), "รบกวนขอรูปภาพประกอบด้วยครับ")
            return
        
    if parts == "part3":
        print("[_submit_parts] Processing part 3...")
        print(f"[CHECK STATE BEFORE PART3] {state}")
        state = _patch_state(user_id, {
            "step": 0,
            "data": {
                "part3": True,
            },
        })
        if not state["data"]["part1"]:
            _reply_cb(state.get("reply_token", ""), "รบกวนขอข้อมูลตามนี้หน่อยครับ\nรหัสสาขาและชื่อสาขา:\nปัญหาที่พบ:\nชื่อ:\nเบอร์ติดต่อ:")
            return
        if not state["data"]["part2"]:
            _reply_cb(state.get("reply_token", ""), "รบกวนขอข้อมูลตามนี้หน่อยครับ\nเครื่อง EDC ค้างหรือไม่\nAns:\nRestart เครื่อง EDC หรือไม่\nAns:\nสลิปจากเครื่องออกหรือไม่\nAns:")
            return

    if state["data"]["part1"] == True and state["data"]["part2"] == True and state["data"]["part3"] == True:
        print("[INFO] Proceeding to summary...")
        data = f"ส่วนที่หนึ่ง: {state['data'].get('text1')}\nส่วนที่สอง: {state['data'].get('text2')}\nส่วนที่สาม: มีรูปภาพประกอบแล้ว "
        _summary(user_id, data)
        return

def _schedule_auto_submit(user_id: str, delay_sec: float = 5.0):
    old = _timers.get(user_id)
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t = threading.Timer(delay_sec, _auto_submit_parts, args=(user_id, "part3"))
    t.daemon = True
    _timers[user_id] = t
    t.start()


def _auto_submit_parts(user_id: str, parts: str, delay_sec: float = 40.0):
    print(f"[_auto_submit_parts] Triggered for user_id {user_id} and parts {parts}")
    old = _timers.get(user_id)
    if old:
        try:
            old.cancel()
        except Exception:
            pass
    t = threading.Timer(delay_sec, _submit_parts, args=(user_id, parts))
    t.daemon = True
    _timers[user_id] = t
    t.start()


def _summary(user_id: str, txt: str) -> str:
    state = _load_state(user_id)
    print("=" * 50)
    print(f"[_summary] [txt] {txt}")
    print(f"[state] {state}")
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
    # resp = fetch(payload)
    resp = {"ok": False}

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


def _handle_edc_message(user_id: str, lower: str, reply_token: str) -> Optional[str]:
    """ตัว test จะมีไว้แยกว่าข้อความที่รับเข้ามาอยู่ใน part ไหนบ้าง หลังจากนั้นข้อมูลของ part นั้นจะถูกส่งต่อไปที่
    send_message เพื่อให้ AI จัดเรียงข้อมูลใหม่ก่อนจะบันทึกลง state อีกครั้ง
    """
    state = _load_state(user_id)

    # ตอนนี้รองรับเฉพาะกรณีเริ่ม flow ใหม่ (step == 0)
    # if state.get("step") != 0:
    #     print("=" * 50)
    #     print(f"[INFO] user {user_id} in progress, ignoring EDC message")
    #     print("=" * 50)
    #     return None

    history = state.get("history", [])
    history.append(lower)
    state = _patch_state(user_id, {
        "reply_token": reply_token,
        "history": history,
        "context_confirm": True,
    })

    part = json.loads(process_message(lower, state))
    res = ''
    
    if part.get("part1"):
        # เข้าข้อมูลที่ลูปค้าพิมพ์มาเก็บเป็น list ชั่วคราว แล้วค่อย join เป็น string ส่งให้ AI แทน
        print("[handle edc message] Processing part 1...")
        latest = _load_state(user_id)
        data = latest.get("data")
        tmp = list(data.get("tmp1"))
        tmp.append(lower)
        state = _patch_state(user_id, {
            "data": {"tmp1": tmp}
        })
        print(f"[CHECK TMP1] {state['data'].get('tmp1')}")
        _auto_submit_parts(user_id, "part1")
        
    if part.get("part2"):
        print("[handle edc message] Processing part 2...")
        latest = _load_state(user_id)
        data = latest.get("data")
        tmp = list(data.get("tmp2"))
        tmp.append(lower)
        state = _patch_state(user_id, {
            "data": {"tmp2": tmp}
        })
        print(f"[CHECK TMP2] {state['data'].get('tmp2')}")
        _auto_submit_parts(user_id, "part2")

    # ถ้า AI ตอบมาครบทุกส่วนแล้วให้ไปสรุปเลย ไม่ต้องส่งข้อความกลับไปอีก
    if ("ส่วนที่สอง:" in res) and ("ส่วนที่สาม:" in res):
        print("[INFO] Proceeding to summary...")
        _summary(user_id, res)
        return None

    # ยังไม่ครบ ให้ส่งข้อความนี้กลับไปถามข้อมูลเพิ่ม แล้ว reset step
    state["step"] = 0
    _save_state(user_id, state)
    # return
    return res


def process_step_message(user_id: str, text: str, reply_token: Optional[str] = None) -> str:
    print("START PROCESS STEP MESSAGE")
    state = _load_state(user_id)
    raw_text = (text or "").strip()
    normalized_text = _normalize_branch_in_text(raw_text)
    print(f"[PATTERN] normalized_text: {normalized_text}")
    predic = predict_classifier.classify(normalized_text)
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
        return "ยกเลิกเซสชันแล้ว"

    prediction = predic.get("prediction")
    reply_text: Optional[str] = None

    if prediction == "edc":
        # กรณีเป็น EDC ให้ไปจัดการในฟังก์ชันเฉพาะ
        print("[INFO] Handling EDC message..." )
        reply_text = _handle_edc_message(user_id, lower, reply_token)
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
    _schedule_auto_submit(user_id, delay_sec=15.0)
    
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


def _normalize_branch_in_text(text: str) -> str:
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
    return f"EDC {edc_freeze}, Slip EDC {edc_slip}"


__all__ = ["process_step_message",
           "process_image_message", "set_reply_callback"]
