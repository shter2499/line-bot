"""
analyze_other_predictions.py
----------------------------
วิเคราะห์ log ของข้อความที่ classifier ทายเป็น 'other'
เพื่อหาข้อความที่อาจทายผิดและควรเพิ่มเข้า training set

Usage:
    # วิเคราะห์ log วันนี้
    python analyze_other_predictions.py
    
    # วิเคราะห์ log วันที่ระบุ
    python analyze_other_predictions.py --date 20260615
    
    # วิเคราะห์ log ช่วงวันที่
    python analyze_other_predictions.py --start-date 20260615 --end-date 20260617
    
    # แสดงเฉพาะข้อความที่มี confidence ต่ำ
    python analyze_other_predictions.py --low-confidence-only
"""
import pandas as pd
import os
import argparse
from datetime import datetime, timedelta


def analyze_log(log_file: str, low_confidence_threshold: float = 0.6):
    """วิเคราะห์ log file เดียว"""
    if not os.path.exists(log_file):
        print(f"❌ File not found: {log_file}")
        return None
    
    df = pd.read_csv(log_file)
    
    if len(df) == 0:
        print(f"ℹ️  No data in {log_file}")
        return None
    
    print(f"\n{'='*70}")
    print(f"📊 Analysis for: {os.path.basename(log_file)}")
    print(f"{'='*70}")
    
    # สถิติพื้นฐาน
    print(f"\n📈 Basic Statistics:")
    print(f"  Total messages: {len(df)}")
    print(f"  Unique users: {df['user_id'].nunique()}")
    print(f"  Average confidence: {df['confidence'].mean():.4f}")
    print(f"  Min confidence: {df['confidence'].min():.4f}")
    print(f"  Max confidence: {df['confidence'].max():.4f}")
    
    # ข้อความที่มี confidence ต่ำ (อาจทายผิด)
    low_conf = df[df['confidence'] < low_confidence_threshold]
    print(f"\n⚠️  Low Confidence Predictions (< {low_confidence_threshold}):")
    print(f"  Count: {len(low_conf)} ({len(low_conf)/len(df)*100:.1f}%)")
    
    if len(low_conf) > 0:
        print(f"\n  Top 10 uncertain predictions:")
        uncertain = low_conf.nsmallest(10, 'confidence')[['text', 'confidence', 'prob_edc']]
        for idx, row in uncertain.iterrows():
            text_preview = row['text'][:60].replace('\\n', ' ')
            print(f"    [{row['confidence']:.3f}] (EDC:{row['prob_edc']:.3f}) {text_preview}...")
    
    # กระจายความมั่นใจ
    print(f"\n📊 Confidence Distribution:")
    bins = [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    dist = pd.cut(df['confidence'], bins=bins).value_counts().sort_index()
    for interval, count in dist.items():
        print(f"  {interval}: {count} ({count/len(df)*100:.1f}%)")
    
    return df


def get_date_range(start_date: str, end_date: str):
    """สร้าง list ของวันที่ระหว่าง start_date และ end_date"""
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def main():
    parser = argparse.ArgumentParser(description="Analyze 'other' prediction logs")
    parser.add_argument("--date", help="Specific date to analyze (YYYYMMDD)")
    parser.add_argument("--start-date", help="Start date for range (YYYYMMDD)")
    parser.add_argument("--end-date", help="End date for range (YYYYMMDD)")
    parser.add_argument("--low-confidence-only", action="store_true", 
                       help="Show only low confidence predictions")
    parser.add_argument("--threshold", type=float, default=0.6,
                       help="Low confidence threshold (default: 0.6)")
    parser.add_argument("--log-dir", default="logs/other_predictions",
                       help="Log directory path")
    parser.add_argument("--export", help="Export uncertain predictions to CSV file")
    args = parser.parse_args()
    
    # กำหนดวันที่ที่จะวิเคราะห์
    dates = []
    if args.date:
        dates = [args.date]
    elif args.start_date and args.end_date:
        dates = get_date_range(args.start_date, args.end_date)
    else:
        # ถ้าไม่ระบุ ใช้วันนี้
        dates = [datetime.now().strftime("%Y%m%d")]
    
    # วิเคราะห์แต่ละวัน
    all_dfs = []
    for date in dates:
        log_file = os.path.join(args.log_dir, f"{date}.csv")
        df = analyze_log(log_file, args.threshold)
        if df is not None:
            all_dfs.append(df)
    
    # สรุปรวม (ถ้ามีหลายวัน)
    if len(all_dfs) > 1:
        combined = pd.concat(all_dfs, ignore_index=True)
        print(f"\n{'='*70}")
        print(f"📊 Combined Summary ({dates[0]} - {dates[-1]})")
        print(f"{'='*70}")
        print(f"  Total messages: {len(combined)}")
        print(f"  Total unique users: {combined['user_id'].nunique()}")
        print(f"  Average confidence: {combined['confidence'].mean():.4f}")
        
        low_conf = combined[combined['confidence'] < args.threshold]
        print(f"  Low confidence messages: {len(low_conf)} ({len(low_conf)/len(combined)*100:.1f}%)")
        
        # Export ถ้าต้องการ
        if args.export:
            uncertain = low_conf.sort_values('confidence')
            uncertain.to_csv(args.export, index=False, encoding='utf-8-sig')
            print(f"\n✅ Exported {len(uncertain)} uncertain predictions to: {args.export}")
    
    # แสดงเฉพาะ low confidence
    elif args.low_confidence_only and len(all_dfs) == 1:
        df = all_dfs[0]
        low_conf = df[df['confidence'] < args.threshold]
        print(f"\n{'='*70}")
        print(f"⚠️  All Low Confidence Predictions:")
        print(f"{'='*70}")
        for idx, row in low_conf.iterrows():
            print(f"\n[{row['timestamp']}] User: {row['user_id']}")
            print(f"  Confidence: {row['confidence']:.4f} (EDC prob: {row['prob_edc']:.4f})")
            print(f"  Text: {row['text']}")


if __name__ == "__main__":
    main()
