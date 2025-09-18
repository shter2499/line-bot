import cv2
import pytesseract
from PIL import Image  # (ยังไม่ใช้มาก แต่เผื่อขยาย)
import re
from datetime import datetime

# ---------------- OCR ขั้นพื้นฐาน ----------------
img = cv2.imread(r'C:/Users/Asus/Desktop/Work/case/S__80355340.jpg')
if img is None:
	raise FileNotFoundError('ไม่พบไฟล์ภาพที่ระบุ')
# blurImg = cv2.medianBlur(img, 1)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)    
custom_lang = '-l tha+eng'

raw_text = pytesseract.image_to_string(gray, config=custom_lang)
# ลบช่องว่างทั้งหมดในแต่ละบรรทัดให้ตัวอักษรติดกัน (ยังคงตัดบรรทัดว่าง)
lines = [
    re.sub(r'\s+', ' ', line.strip())
    for line in raw_text.splitlines()
    if line.strip()
]
ocr_text = '\n'.join(lines)
print(f'[data] {ocr_text}')

# ---------------- ฟังก์ชันตรวจจับ ธนาคาร / วันที่ เวลา ----------------
BANK_KEYWORDS = {
	'กสิกร': 'กสิกร', 'kbank': 'กสิกร', 'k+': 'กสิกร','ธ.กสิกรไทย':'กสิกร',
	'ไทยพาณิชย์': 'ไทยพาณิชย์', 'scb': 'ไทยพาณิชย์',
	'กรุงไทย': 'กรุงไทย', 'krungthai': 'กรุงไทย',
	'กรุงเทพ': 'กรุงเทพ', 'bbl': 'กรุงเทพ','ธนาคารกรุงเทพ':'กรุงเทพ','Bangkok Bank':'กรุงเทพ',
	'กรุงศรี': 'กรุงศรี', 'bay': 'กรุงศรี',
	'ออมสิน': 'ออมสิน', 'gsb': 'ออมสิน',
	'ttb': 'TTB', 'tmb': 'TTB',
	'uob': 'UOB', 'cimb': 'CIMB',
	'truemoney':'TrueMoney','ทรูมันนี่':'TrueMoney'
}

THAI_MONTHS = {
	'ม.ค': 1, 'มกราคม': 1,
	'ก.พ': 2, 'กุมภาพันธ์': 2,
	'มี.ค': 3, 'มีนาคม': 3,
	'เม.ย': 4, 'เมษายน': 4,
	'พ.ค': 5, 'พฤษภาคม': 5,
	'มิ.ย': 6, 'มิถุนายน': 6,
	'ก.ค': 7, 'กรกฎาคม': 7,
	'ส.ค': 8, 'สิงหาคม': 8,
	'ก.ย': 9, 'กันยายน': 9,
	'ต.ค': 10, 'ตุลาคม': 10,
	'พ.ย': 11, 'พฤศจิกายน': 11,
	'ธ.ค': 12, 'ธันวาคม': 12,
}

TIME_PATTERN = re.compile(r'(\b\d{1,2})[:.](\d{2})(?::(\d{2}))?')
DATETIME_LINE_PATTERN = re.compile(r'(\d{1,2})\s+([A-Za-zก-ฮ\.]+)\s+(\d{2,4}),?\s*(\d{1,2})[:.](\d{2})(?::(\d{2}))?')

def extract_bank(text: str):
	low = text.lower()
	for key, value in BANK_KEYWORDS.items():
		if key in low:
			return value
	return None

def extract_datetime(text: str):
	# พยายามจับรูปแบบรวมในบรรทัดเดียว เช่น "30 มิ.ย. 68,14:52" หรือ "30 มิ.ย. 2568 14:52:10"
	for line in text.splitlines():
		line_strip = line.strip()
		if not line_strip:
			continue
		m = DATETIME_LINE_PATTERN.search(line_strip)
		if not m:
			continue
		day_s, month_token, year_s, h_s, min_s, sec_s = m.groups()
		day = int(day_s)
		month_key = month_token.strip('.').strip()
		if month_key not in THAI_MONTHS:
			continue
		month = THAI_MONTHS[month_key]
		year = int(year_s)
		if len(year_s) == 2:  # ปีสองหลัก -> พ.ศ.
			year += 2500
		if year > 2400:  # พ.ศ. -> ค.ศ.
			year -= 543
		hour = int(h_s)
		minute = int(min_s)
		second = int(sec_s) if sec_s else 0
		try:
			dt = datetime(year, month, day, hour, minute, second)
			return dt.isoformat(sep=' ')
		except ValueError:
			continue

	# ถ้าไม่เจอใช้วิธีเดิม (เดือน + เวลา อยู่กระจัดกระจายในไลน์)
	candidates = []
	for line in text.splitlines():
		line_strip = line.strip()
		if not line_strip:
			continue
		if any(mo in line_strip for mo in THAI_MONTHS) and TIME_PATTERN.search(line_strip):
			candidates.append(line_strip)
	if not candidates:
		return None
	line = candidates[0]
	tm = TIME_PATTERN.search(line)
	if not tm:
		return None
	h, m_, s_ = tm.group(1), tm.group(2), tm.group(3)
	hour = int(h); minute = int(m_); second = int(s_) if s_ else 0
	tokens = re.split(r'\s+', line)
	day = month = year = None
	for t in tokens:
		t_clean = t.strip().strip('.')
		if day is None and t_clean.isdigit() and 1 <= len(t_clean) <= 2:
			day = int(t_clean); continue
		if month is None and t_clean in THAI_MONTHS:
			month = THAI_MONTHS[t_clean]; continue
		if month and year is None and t_clean.isdigit() and (len(t_clean) in (2,4)):
			y = int(t_clean)
			if len(t_clean) == 2:
				y += 2500
			if y > 2400:
				y -= 543
			year = y
	if None in (day, month, year):
		return None
	try:
		dt = datetime(year, month, day, hour, minute, second)
		return dt.isoformat(sep=' ')
	except ValueError:
		return None

# ---------------- ใช้งานฟังก์ชัน ----------------
bank_name = extract_bank(ocr_text)
dt_text = extract_datetime(ocr_text)
print(f'[bank] {bank_name or "ไม่พบ"}')
print(f'[datetime] {dt_text or "ไม่พบ"}')